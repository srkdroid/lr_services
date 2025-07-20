import os
import requests
import logging
from playwright.sync_api import sync_playwright, TimeoutError

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

def send_telegram_message(message_text):
    """Sends a message to the configured Telegram chat."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("Telegram credentials are not set. Cannot send message.")
        return

    # Telegram has a message size limit of 4096 characters.
    # This loop splits long messages into multiple chunks.
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
        try:
            logging.info("Launching browser...")
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            logging.info(f"Navigating to {BHOOMI_URL}")
            # Increased timeout for initial page load to 2 minutes
            page.goto(BHOOMI_URL, timeout=120000) 

            # --- Interacting with the Form ---
            logging.info(f"Selecting District: {DISTRICT_NAME}")
            page.select_option("select#district", label=DISTRICT_NAME)
            page.wait_for_timeout(3000) # Added a 3-second pause

            logging.info(f"Selecting Taluk: {TALUK_NAME}")
            page.select_option("select#taluk", label=TALUK_NAME)
            page.wait_for_timeout(3000) # Added a 3-second pause

            logging.info(f"Selecting Hobli: {HOBLI_NAME}")
            page.select_option("select#hobli", label=HOBLI_NAME)
            page.wait_for_timeout(3000) # Added a 3-second pause

            logging.info(f"Selecting Village: {VILLAGE_NAME}")
            page.select_option("select#village", label=VILLAGE_NAME)
            page.wait_for_timeout(1000) # Short pause before clicking

            logging.info("Clicking 'Fetch Details' button...")
            page.click('button:has-text("Fetch Details")')

            # --- Scraping the Results Table ---
            logging.info("Waiting for transaction details table to load...")
            # Increased timeout for results table to 1 minute (60000 ms)
            page.wait_for_selector('//div[@id="transland"]//table/tbody/tr', timeout=60000)

            rows = page.query_selector_all('//div[@id="transland"]//table/tbody/tr')
            if not rows:
                logging.info("No transaction data found for the selected criteria.")
                send_telegram_message(f"✅ Bhoomi Bot: No new transaction data found for {VILLAGE_NAME} village.")
                return

            logging.info(f"Found {len(rows)} transaction(s). Formatting message...")

            header_elements = page.query_selector_all('//div[@id="transland"]//table/thead/tr/th')
            headers = [h.inner_text().strip() for h in header_elements]

            message_lines = [f"📄 *Bhoomi Mutation Status for {VILLAGE_NAME}*"]
            message_lines.append("--------------------------------------")

            for row in rows:
                cells = row.query_selector_all('td')
                record_details = [f"*{headers[i+1]}*: {cells[i+1].inner_text().strip()}" for i in range(len(headers)-1)]
                message_lines.append("\n".join(record_details))
                message_lines.append("--------------------------------------")

            final_message = "\n".join(message_lines)
            send_telegram_message(final_message)
            logging.info("Successfully sent data to Telegram.")

        except TimeoutError:
            error_message = "A timeout occurred. The website might be down, the page structure might have changed, or the results took too long to load."
            logging.error(error_message)
            send_telegram_message(f"❌ *Bhoomi Bot Error*: {error_message}")
        except Exception as e:
            error_message = f"An unexpected error occurred: {e}"
            logging.error(error_message, exc_info=True)
            send_telegram_message(f"❌ *Bhoomi Bot Error*: An unexpected error occurred. Check the GitHub Actions logs for details.")
        finally:
            if browser:
                logging.info("Closing browser.")
                browser.close()

if __name__ == "__main__":
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("CRITICAL ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables must be set in GitHub Secrets.")
    else:
        scrape_bhoomi_data()
