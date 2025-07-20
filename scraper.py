import os
import requests
import logging
from playwright.sync_api import sync_playwright, TimeoutError
from playwright_stealth import stealth_sync

# --- Configuration ---
# Set up basic logging to see the script's progress in GitHub Actions logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# The target website
BHOOMI_URL = "https://landrecords.karnataka.gov.in/service60/"

# --- IMPORTANT: Set the values for the dropdowns you want to query ---
# The values MUST match the text in the dropdowns exactly.
# This example uses Bengaluru Urban -> Bengaluru East -> Varthur -> Bellandur.

DISTRICT_NAME = "ಚಾಮರಾಜನಗರ"
TALUK_NAME = "ಕೊಳ್ಳೇಗಾಲ (ಹನೂರು)"
HOBLI_NAME = "ಹನೂರು"
VILLAGE_NAME = "ಹುಲ್ಲೇಪುರ"


# Telegram configuration will be read from environment variables (GitHub Secrets)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
SCREENSHOT_FILE = "error_screenshot.png"

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
    with sync_playwright() as p:
        browser = None
        page = None
        try:
            logging.info("Launching browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Apply stealth measures to make the browser look like a real user
            logging.info("Applying stealth measures...")
            stealth_sync(page)

            logging.info(f"Navigating to {BHOOMI_URL}")
            page.goto(BHOOMI_URL, timeout=120000, wait_until='domcontentloaded')

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
            error_message = f"An error occurred: {e.__class__.__name__}. Check logs for details."
            logging.error(f"An unexpected error occurred: {e}", exc_info=True)
            
            # Take a screenshot on error for debugging
            if page:
                logging.info(f"Saving screenshot to {SCREENSHOT_FILE}")
                page.screenshot(path=SCREENSHOT_FILE, full_page=True)
            
            send_telegram_message(f"❌ *Bhoomi Bot Error*: {error_message}. A screenshot was saved to the GitHub Actions artifacts.")
            # Re-raise the exception to ensure the GitHub Actions step fails
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
