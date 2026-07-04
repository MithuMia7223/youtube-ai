import json
import os

AFFILIATE_FILE = "affiliate_links.json"

DEFAULT_OFFERS = {
    "AI": {
        "product_name": "Gemini & AI Automation Tools",
        "description": "Start building your own AI bots and automate your life.",
        "link": "https://www.hostinger.com/antigravity-ai" # Fallback high-paying affiliate link (hosting/tech)
    },
    "Finance": {
        "product_name": "Top Investment & Crypto Trading App",
        "description": "Get free stock or trading bonus when you sign up using this link.",
        "link": "https://binance.com/activity/referral"
    },
    "Motivation": {
        "product_name": "Audible Free Trial (Get 2 Free Audiobooks)",
        "description": "Listen to the best motivational books for free on your daily commute.",
        "link": "https://amzn.to/3zAudible"
    },
    "Tech": {
        "product_name": "Premium High-Speed Web Hosting (75% OFF)",
        "description": "The best hosting for starting your automated online blogs and business.",
        "link": "https://www.hostgator.com/promo"
    },
    "General": {
        "product_name": "Start Your Freelancing Journey on Fiverr",
        "description": "Find top services or sell your skills online and earn in USD.",
        "link": "https://fiverr.com/referral"
    }
}

def load_links() -> dict:
    if os.path.exists(AFFILIATE_FILE):
        try:
            with open(AFFILIATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Save default if not exists
    with open(AFFILIATE_FILE, 'w') as f:
        json.dump(DEFAULT_OFFERS, f, indent=2)
    return DEFAULT_OFFERS

def save_link(niche: str, product_name: str, link: str, description: str = ""):
    data = load_links()
    data[niche] = {
        "product_name": product_name,
        "description": description,
        "link": link
    }
    with open(AFFILIATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_affiliate_text(niche_keyword: str) -> str:
    """Find matching affiliate link based on niche keyword and return a formatted CTA block."""
    data = load_links()
    
    selected = data.get("General")
    niche_lower = niche_keyword.lower()
    
    if "ai" in niche_lower or "technology" in niche_lower or "future" in niche_lower:
        selected = data.get("AI")
    elif "finance" in niche_lower or "money" in niche_lower or "rich" in niche_lower or "invest" in niche_lower:
        selected = data.get("Finance")
    elif "motivation" in niche_lower or "mindset" in niche_lower or "success" in niche_lower:
        selected = data.get("Motivation")
    elif "tech" in niche_lower or "gadget" in niche_lower or "programming" in niche_lower:
        selected = data.get("Tech")
        
    return f"\n\n━━━━━━━━━━━━━━━━━━━━\n🎁 RECOMMENDED RESOURCE FOR YOU:\n👉 Get {selected['product_name']}: {selected['link']}\n({selected['description']})\n━━━━━━━━━━━━━━━━━━━━\n"
