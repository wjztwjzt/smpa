import re
import json
import asyncio
import requests
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import os
load_dotenv()
PAGES = [
    "https://duihuan.smzdm.com/lipin/",
    "https://duihuan.smzdm.com/lipin/p2/",
]

# Telegram 配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")


async def scrape_page(page, url):
    print(f"正在抓取: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # 等待 JS 渲染完成
    await page.wait_for_timeout(3000)
    # 等待列表加载
    await page.wait_for_selector("li.exchange-item", timeout=15000)

    items = await page.evaluate("""() => {
        const items = [];
        document.querySelectorAll('li.exchange-item').forEach(li => {
            const linkEl = li.querySelector('a.exchange-link');
            if (!linkEl) return;
            const href = linkEl.getAttribute('href');
            const idMatch = href.match(/\\/d\\/(\\d+)\\//);
            if (!idMatch) return;
            const id = idMatch[1];
            const name = linkEl.textContent.trim();

            const statsEl = li.querySelector('.ticket-info-top');
            const statsText = statsEl ? statsEl.textContent.trim() : '';

            const claimedMatch = statsText.match(/已领[：:]\\s*([\\d,]+)\\s*(张|件)/);
            const remainMatch = statsText.match(/剩余[：:]\\s*([\\d,]+)\\s*(张|件)/);

            const costEl = li.querySelector('.ticket-info-bottom span');
            const costText = costEl ? costEl.textContent.trim() : '';

            let cost = null;
            let costType = null;
            const silverMatch = costText.match(/([\\d,]+)\\s*碎银子/);
            const goldMatch = costText.match(/([\\d,]+)\\s*金币/);
            if (silverMatch) {
                cost = parseInt(silverMatch[1].replace(/,/g, ''));
                costType = '碎银子';
            } else if (goldMatch) {
                cost = parseInt(goldMatch[1].replace(/,/g, ''));
                costType = '金币';
            }

            // 只收集碎银子商品
            if (costType !== '碎银子') return;

            items.push({
                id: id,
                name: name,
                cost: cost,
                claimed: claimedMatch ? parseInt(claimedMatch[1].replace(/,/g, '')) : null,
                remaining: remainMatch ? parseInt(remainMatch[1].replace(/,/g, '')) : null,
                url: 'https://duihuan.smzdm.com/d/' + id + '/',
            });
        });
        return items;
    }""")

    print(f"  获取到 {len(items)} 个碎银子商品")
    return items


async def main_async():
    print("=" * 60)
    print("什么值得买 - 碎银子礼品卡爬虫 (>= 500 碎银子)")
    print("=" * 60)

    all_items = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--ignore-certificate-errors",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            java_script_enabled=True,
            bypass_csp=True,
        )
        page = await context.new_page()
        await page.add_init_script("""
            // 移除 webdriver 标记
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            // 伪造 plugins
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5], length: 5 });
            // 伪造 languages
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
            // 伪造 chrome runtime
            window.chrome = { runtime: {} };
            // 伪造 permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
            // 覆盖 headless 检测
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        for url in PAGES:
            items = await scrape_page(page, url)
            all_items.extend(items)

        await browser.close()

    # 筛选: 碎银子 >= 500
    filtered = [item for item in all_items if item["cost"] and item["cost"] >= 500]
    filtered.sort(key=lambda x: x["cost"])

    print(f"\n共找到 {len(filtered)} 个 >= 500 碎银子的礼品项目:\n")

    # 表格输出
    print(f"{'ID':<10} {'名称':<35} {'碎银子':<10} {'已领':<14} {'剩余':<10}")
    print("-" * 82)
    for item in filtered:
        claimed_str = f"{item['claimed']}张/件" if item['claimed'] is not None else "-"
        remain_str = f"{item['remaining']}张/件" if item['remaining'] is not None else "-"
        print(f"{item['id']:<10} {item['name']:<35} {item['cost']:<10} {claimed_str:<14} {remain_str:<10}")

    # 保存 JSON
    with open("smzdm_gifts.json", "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 smzdm_gifts.json")

    # 输出 ID 列表
    print(f"\nID 列表: {', '.join(item['id'] for item in filtered)}")

    return filtered


def build_telegram_message(items):
    lines = [f"📊 什么值得买 碎银子礼品卡 (>=500 碎银子)",
             f"共 {len(items)} 个项目\n"]
    for i, item in enumerate(items, 1):
        unit = item.get("unit", "张")
        claimed_str = f"{item['claimed']}{'张' if '张' in str(item.get('claimed', '')) else '张/件'}"
        remain_str = f"{item['remaining']}{'张' if item['remaining'] is not None else '-'}"
        lines.append(f"{i}. [{item['id']}] {item['name']}")
        lines.append(f"   碎银: {item['cost']} | 已领: {claimed_str} | 剩余: {remain_str}")
        lines.append(f"   {item['url']}")
    return "\n".join(lines)


def send_telegram(items):
    if not items:
        print("没有数据需要发送")
        return

    msg = build_telegram_message(items)
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": msg,
            "disable_web_page_preview": True
        }, timeout=15)
        if resp.status_code == 200 and resp.json().get("ok"):
            print("Telegram 消息发送成功")
        else:
            print(f"Telegram 发送失败: {resp.text[:200]}")
    except Exception as e:
        print(f"Telegram 发送异常: {e}")


def main():
    items = asyncio.run(main_async())
    if items:
        send_telegram(items)


if __name__ == "__main__":
    main()
