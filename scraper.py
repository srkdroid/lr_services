import os
import requests
import logging
import random
from playwright.sync_api import sync_playwright, TimeoutError

# --- Configuration ---
# Set up basic logging to see the script's progress in GitHub Actions logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# The target website
BHOOMI_URL = "https://landrecords.karnataka.gov.in/service60/"

# --- IMPORTANT: Set the values for the dropdowns you want to query ---
# The values MUST match the text in the dropdowns exactly.
DISTRICT_NAME = "ಚಾಮರಾಜನಗರ"
TALUK_NAME = "ಕೊಳ್ಳೇಗಾಲ (ಹನೂರು)"
HOBLI_NAME = "ಹನೂರು"
VILLAGE_NAME = "ಹುಲ್ಲೇಪುರ"

# Telegram configuration will be read from environment variables (GitHub Secrets)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
SCREENSHOT_FILE = "error_screenshot.png"

def get_free_proxies():
    """Fetches a list of free proxies from a public API."""
    logging.info("Fetching a list of free proxies...")
    try:
        # Using a reliable public API for free proxies
        response = requests.get("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all", timeout=20)
        if response.status_code == 200:
            proxies = response.text.strip().split("\r\n")
            random.shuffle(proxies) # Shuffle to try different proxies each run
            logging.info(f"Successfully fetched {len(proxies)} proxies.")
            return proxies
    except requests.RequestException as e:
        logging.error(f"Could not fetch proxies: {e}")
    return []

def send_telegram_message(message_text):
    """Sends a message to the configured Telegram chat."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Telegram credentials are not set. Cannot send message.")
        return

    # Telegram has a message size limit of 4096 characters.
    for i in range(0, len(message_text), 4096):
        chunk = message_text[i:i + 4096]
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': chunk,
            'parse_mode': 'Markdown'
        }
        try:
            response = requests.post(TELEGRAM_API_URL, data=payload, timeout=10)
            if response.status_code != 200:
                logging.error(f"Failed to send Telegram message. Status: {response.status_code}, Response: {response.text}")
        except requests.RequestException as e:
            logging.error(f"An error occurred while sending Telegram message: {e}")

def scrape_bhoomi_data():
    """Launches a browser, navigates the site, scrapes data, and sends it."""
    proxies = get_free_proxies()
    if not proxies:
        send_telegram_message("❌ *Bhoomi Bot Error*: Could not fetch any proxies to use. Aborting run.")
        return

    page = None
    browser = None
    context = None
    
    with sync_playwright() as p:
        # Try up to 10 different proxies before giving up
        for i, proxy_server in enumerate(proxies[:10]):
            try:
                logging.info(f"Attempt {i+1}/10: Trying with proxy: {proxy_server}")
                browser = p.firefox.launch(
                    headless=True,
                    proxy={"server": f"http://{proxy_server}"}
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                    ignore_https_errors=True # Important for some proxies
                )
                page = context.new_page()

                logging.info(f"Navigating to {BHOOMI_URL} via proxy...")
                page.goto(BHOOMI_URL, timeout=90000, wait_until='domcontentloaded')
                
                # If we reach here, the connection was successful
                logging.info("Successfully connected to the website through the proxy.")
                break # Exit the loop and proceed with scraping

            except Exception as e:
                logging.warning(f"Proxy {proxy_server} failed: {e.__class__.__name__}. Trying next proxy.")
                if browser:
                    browser.close()
                if (i + 1) == 10: # If it was the last attempt
                    # Re-raise the last exception to fail the workflow
                    raise e

        # --- The rest of the script runs only if a connection was successful ---
        try:
            # --- Interacting with the Form ---
            logging.info(f"Selecting District: {DISTRICT_NAME}")
            page.locator("select#district").select_option(label=DISTRICT_NAME)
            page.wait_for_load_state('networkidle', timeout=20000)

            logging.info(f"Selecting Taluk: {TALUK_NAME}")
            page.locator("select#taluk").select_option(label=TALUK_NAME)
            page.wait_for_load_state('networkidle', timeout=20000)

            logging.info(f"Selecting Hobli: {HOBLI_NAME}")
            page.locator("select#hobli").select_option(label=HOBLI_NAME)
            page.wait_for_load_state('networkidle', timeout=20000)

            logging.info(f"Selecting Village: {VILLAGE_NAME}")
            page.locator("select#village").select_option(label=VILLAGE_NAME)
            page.wait_for_load_state('networkidle', timeout=10000)

            logging.info("Clicking 'Fetch Details' button...")
            page.locator('button:has-text("Fetch Details")').click()

            # --- Scraping the Results Table ---
            logging.info("Waiting for transaction details table to load...")
            table_selector = '//div[@id="transland"]//table/tbody/tr'
            page.wait_for_selector(table_selector, timeout=60000)

            rows = page.locator(table_selector).all()
            if not rows:
                logging.info("No transaction data found for the selected criteria.")
                send_telegram_message(f"✅ Bhoomi Bot: No new transaction data found for {VILLAGE_NAME} village.")
                return

            logging.info(f"Found {len(rows)} transaction(s). Formatting message...")
            header_elements = page.locator('//div[@id="transland"]//table/thead/tr/th').all()
            headers = [h.inner_text().strip() for h in header_elements]

            message_lines = [f"📄 *Bhoomi Mutation Status for {VILLAGE_NAME}*"]
            message_lines.append("--------------------------------------")

            for row in rows:
                cells = row.locator('td').all()
                record_details = [f"*{headers[i+1]}*: {cells[i+1].inner_text().strip()}" for i in range(len(headers)-1)]
                message_lines.append("\n".join(record_details))
                message_lines.append("--------------------------------------")

            final_message = "\n".join(message_lines)
            send_telegram_message(final_message)
            logging.info("Successfully sent data to Telegram.")

        except Exception as e:
            error_message = f"An error occurred after connecting: {e.__class__.__name__}. Check logs."
            logging.error(f"An unexpected error occurred: {e}", exc_info=True)
            if page:
                logging.info(f"Saving screenshot to {SCREENSHOT_FILE}")
                page.screenshot(path=SCREENSHOT_FILE, full_page=True)
            send_telegram_message(f"❌ *Bhoomi Bot Error*: {error_message}. A screenshot was saved to the GitHub Actions artifacts.")
            raise
        finally:
            if browser:
                logging.info("Closing browser.")
                browser.close()

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("CRITICAL ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables must be set in GitHub Secrets.")
    else:
        scrape_bhoomi_data()
