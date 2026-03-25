"""Receipt OCR service using Claude Vision API."""

import base64
import json
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import aiosqlite

from anthropic import AsyncAnthropic

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedReceiptData:
    """Extracted receipt data."""
    amount: float
    currency: str
    description: str
    merchant: Optional[str] = None
    transaction_date: Optional[date] = None


class ReceiptService:
    """Service for processing receipt images with Claude Vision."""

    EXTRACTION_PROMPT = """You are analyzing an image of a receipt, invoice, or payment record (including app screenshots of ride-sharing, food delivery, banking, etc.).

IMPORTANT: If the document shows a single invoice or bill with a TOTAL/SUBTOTAL/GRAND TOTAL line, return ONLY that single total as one entry — do NOT itemize individual line items. Use the highest-level total amount visible (e.g. "Total due", "Grand total", "Amount payable").

Only return multiple entries if the document genuinely contains multiple separate transactions (e.g. a bank statement, a list of rides, multiple receipts on one page).

Skip any cancelled, voided, or zero-amount entries.

Return ONLY a JSON array where each item has:
- amount: The amount paid (number only, no currency symbol)
- currency: The currency code (USD, EUR, GBP, BRL, etc.)
- description: A brief description of the purchase (e.g., "taxi", "groceries", "consulting services")
- merchant: The merchant/vendor name (if visible)
- date: The transaction date in YYYY-MM-DD format (if visible)

If you cannot determine a field, use null.
Return ONLY valid JSON array, nothing else. Example:
[{"amount": 14.95, "currency": "BRL", "description": "ride to Olegário Cabeleireiros", "merchant": "Uber", "date": "2025-02-10"}, {"amount": 15.96, "currency": "BRL", "description": "ride to Hospital Sírio Libanês", "merchant": "Uber", "date": "2025-02-10"}]"""

    def __init__(self, db: aiosqlite.Connection):
        """
        Initialize receipt service.

        Args:
            db: Database connection
        """
        self.db = db
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def extract_from_image(self, image_data: bytes, media_type: str = "image/jpeg") -> tuple[list[ExtractedReceiptData], Optional[str]]:
        """
        Extract expense data from receipt image using Claude Vision.

        Returns:
            Tuple of (list of ExtractedReceiptData, error_message or None)
        """
        try:
            data_base64 = base64.b64encode(image_data).decode('utf-8')

            if media_type == "application/pdf":
                content_block = {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": data_base64,
                    },
                }
            else:
                content_block = {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data_base64,
                    },
                }

            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            content_block,
                            {
                                "type": "text",
                                "text": self.EXTRACTION_PROMPT
                            }
                        ],
                    }
                ],
            )

            response_text = response.content[0].text.strip()
            logger.info(f"Claude Vision response: {response_text}")

            if not response_text:
                logger.warning("Claude returned empty response for receipt image")
                return ([], None)

            # Extract JSON - handle markdown fences or mixed text
            json_text = response_text
            if '```' in response_text:
                import re
                match = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```', response_text, re.DOTALL)
                if match:
                    json_text = match.group(1)
            elif not response_text.startswith(('[', '{')):
                import re
                match = re.search(r'(\[.*\]|\{.*\})', response_text, re.DOTALL)
                if match:
                    json_text = match.group(1)

            parsed = json.loads(json_text)

            # Normalise: accept both a single object and an array
            items = parsed if isinstance(parsed, list) else [parsed]

            results = []
            for item in items:
                receipt = self._convert_to_receipt_data(item)
                if receipt:
                    results.append(receipt)

            if results:
                return (results, None)
            else:
                logger.warning(f"All items failed conversion. Raw response: {response_text}")
                return ([], "Could not extract required fields from receipt")

        except Exception as e:
            logger.error(f"Failed to extract receipt data: {e}", exc_info=True)
            error_str = str(e)
            if "credit balance is too low" in error_str or "billing" in error_str.lower():
                return ([], "⚠️ Anthropic API credits depleted. Please add credits at console.anthropic.com or enter the expense manually.")
            elif "api key" in error_str.lower() or "authentication" in error_str.lower():
                return ([], "⚠️ Anthropic API authentication error. Please check your API key.")
            else:
                return ([], None)

    def _convert_to_receipt_data(self, data: dict) -> Optional[ExtractedReceiptData]:
        """
        Convert API response to ExtractedReceiptData.

        Args:
            data: Extracted data dictionary

        Returns:
            ExtractedReceiptData or None if invalid
        """
        try:
            # Required fields - accept either 'amount' (new) or 'total_amount' (legacy)
            raw_amount = data.get('amount') or data.get('total_amount')
            if not raw_amount:
                logger.warning(f"Missing amount in extracted data: {data}")
                return None

            amount = float(raw_amount)
            # Currency is optional — fall back to DEFAULT so the chat default applies
            raw_currency = data.get('currency')
            currency = self._normalize_currency(raw_currency) if raw_currency else 'DEFAULT'
            description = data.get('description', 'expense')

            # Optional fields
            merchant = data.get('merchant')
            transaction_date = None
            if data.get('date'):
                try:
                    transaction_date = date.fromisoformat(data['date'])
                except ValueError:
                    logger.warning(f"Invalid date format: {data['date']}")

            return ExtractedReceiptData(
                amount=amount,
                currency=currency,
                description=description,
                merchant=merchant,
                transaction_date=transaction_date
            )

        except Exception as e:
            logger.error(f"Failed to convert extracted data: {e}")
            return None

    def _normalize_currency(self, currency_str: str) -> str:
        """
        Normalize currency symbol or code to standard code.

        Args:
            currency_str: Currency string (code or symbol)

        Returns:
            Normalized currency code
        """
        # Map of symbols to codes
        symbol_map = settings.currency_symbols

        # Check if it's a symbol
        if currency_str in symbol_map:
            return symbol_map[currency_str]

        # Assume it's already a code
        return currency_str.upper()

    async def store_pending_confirmation(
        self,
        chat_id: int,
        user_telegram_id: int,
        confirmation_message_id: int,
        receipt_file_id: str,
        extracted_data: list[ExtractedReceiptData]
    ) -> None:
        """
        Store pending confirmation in database.

        Args:
            chat_id: Telegram chat ID
            user_telegram_id: Telegram user ID
            confirmation_message_id: Message ID of bot's confirmation
            receipt_file_id: Telegram file ID of receipt image
            extracted_data: Extracted receipt data
        """
        expires_at = datetime.now() + timedelta(seconds=settings.RECEIPT_CONFIRMATION_TIMEOUT)

        # Serialise the full list of expenses as JSON into extracted_description.
        # extracted_amount / currency store the first item for backwards compat.
        first = extracted_data[0]
        items_json = json.dumps([
            {
                "amount": e.amount,
                "currency": e.currency,
                "description": e.description,
                "merchant": e.merchant,
                "date": e.transaction_date.isoformat() if e.transaction_date else None,
            }
            for e in extracted_data
        ])

        await self.db.execute(
            """
            INSERT INTO pending_confirmations (
                chat_id, user_telegram_id, confirmation_message_id,
                receipt_file_id, extracted_amount, extracted_currency,
                extracted_description, extracted_merchant, extracted_date,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id, user_telegram_id, confirmation_message_id,
                receipt_file_id, first.amount, first.currency,
                items_json, first.merchant,
                first.transaction_date.isoformat() if first.transaction_date else None,
                expires_at.isoformat()
            )
        )
        await self.db.commit()

    async def get_pending_confirmation(
        self,
        chat_id: int,
        user_telegram_id: int
    ) -> Optional[dict]:
        """
        Get pending confirmation for a user.

        Args:
            chat_id: Telegram chat ID
            user_telegram_id: Telegram user ID

        Returns:
            Pending confirmation data or None
        """
        cursor = await self.db.execute(
            """
            SELECT id, confirmation_message_id, receipt_file_id,
                   extracted_amount, extracted_currency, extracted_description,
                   extracted_merchant, extracted_date, expires_at
            FROM pending_confirmations
            WHERE chat_id = ? AND user_telegram_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, user_telegram_id)
        )
        row = await cursor.fetchone()

        if row:
            expires_at = datetime.fromisoformat(row[8])
            if datetime.now() > expires_at:
                # Expired, delete it
                await self.delete_pending_confirmation(row[0])
                return None

            return {
                'id': row[0],
                'confirmation_message_id': row[1],
                'receipt_file_id': row[2],
                'amount': row[3],
                'currency': row[4],
                'description': row[5],
                'merchant': row[6],
                'transaction_date': date.fromisoformat(row[7]) if row[7] else None,
            }

        return None

    async def delete_pending_confirmation(self, confirmation_id: int) -> None:
        """
        Delete pending confirmation.

        Args:
            confirmation_id: Confirmation ID
        """
        await self.db.execute(
            "DELETE FROM pending_confirmations WHERE id = ?",
            (confirmation_id,)
        )
        await self.db.commit()

    async def cleanup_expired_confirmations(self) -> int:
        """
        Clean up expired pending confirmations.

        Returns:
            Number of confirmations deleted
        """
        cursor = await self.db.execute(
            "DELETE FROM pending_confirmations WHERE expires_at < ?",
            (datetime.now().isoformat(),)
        )
        await self.db.commit()
        return cursor.rowcount
