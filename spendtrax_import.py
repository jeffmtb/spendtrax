#!/usr/bin/env python3
"""
SpendTrax 2.0 - CSV to SQLite Transaction Importer
Consolidates multiple bank/credit card CSV files into a single SQLite database
Supports multi-year data with consolidated categories
"""

import pandas as pd
import sqlite3
import os
import re
import glob
import math
from datetime import datetime
from typing import Dict, List, Tuple, Optional


class InputValidationError(ValueError):
    """Raised when a CSV cannot be validated for a known account format."""


class SpendTraxImporter:
    def __init__(self, db_path: str = "spendtrax.db"):
        """Initialize SpendTrax with database path"""
        self.db_path = db_path
        self.conn = None
        self.validation_errors = []

        # Fewer retirement-planning buckets with a simple essential/non-essential flag.
        self.categories = {
            'Housing & Utilities': True,
            'Food & Dining': True,
            'Transportation': True,
            'Health & Wellness': True,
            'Personal & Household': False,
            'Travel & Entertainment': False,
            'Giving': False,
        }

        # Map incoming and legacy categories to the smaller planning buckets.
        self.category_mapping = {
            'gas': 'Transportation',
            'automotive': 'Transportation',
            'auto & transport': 'Transportation',
            'automotive & gas': 'Transportation',
            'gas/automotive': 'Transportation',
            'groceries': 'Food & Dining',
            'food & drink': 'Food & Dining',
            'food & dining': 'Food & Dining',
            'dining': 'Food & Dining',
            'shopping': 'Personal & Household',
            'merchandise': 'Personal & Household',
            'shopping & merchandise': 'Personal & Household',
            'travel': 'Travel & Entertainment',
            'lodging': 'Travel & Entertainment',
            'other travel': 'Travel & Entertainment',
            'entertainment': 'Travel & Entertainment',
            'home': 'Housing & Utilities',
            'bills & utilities': 'Housing & Utilities',
            'utilities': 'Housing & Utilities',
            'phone/cable': 'Housing & Utilities',
            'internet': 'Housing & Utilities',
            'insurance': 'Housing & Utilities',
            'health & wellness': 'Health & Wellness',
            'health care': 'Health & Wellness',
            'health': 'Health & Wellness',
            'health & fitness': 'Health & Wellness',
            'pets': 'Health & Wellness',
            'personal': 'Personal & Household',
            'personal & miscellaneous': 'Personal & Household',
            'professional services': 'Personal & Household',
            'services': 'Personal & Household',
            'other services': 'Personal & Household',
            'fees & adjustments': 'Personal & Household',
            'fee/interest charge': 'Personal & Household',
            'other': 'Personal & Household',
            'gifts': 'Giving',
            'donations': 'Giving',
            'gifts & donations': 'Giving',
            'giving': 'Giving',
        }

        # Patterns to identify grocery stores (for Food & Drink categorization)
        self.grocery_store_patterns = [
            r'wholefds', r'whole foods', r'king soopers', r'natural grocers',
            r'trader joe', r'safeway', r'kroger', r'aldi', r'costco(?!.*gas)',
            r'walmart(?!.*gas)', r'target(?!.*gas)', r'hy[- ]vee', r'publix',
            r'wegmans', r'sprouts', r'lucky[\' ]s market', r'bakers'
        ]

        # Patterns to identify credit card payments (to exclude from checking)
        self.credit_card_payment_patterns = [
            r'chase credit crd',
            r'capital one',
            r'firsttech.*credit',
            r'credit card.*payment',
            r'payment.*thank you',
        ]

        # Patterns to exclude from checking (transfers, investments, tuition, etc.)
        self.checking_exclusion_patterns = [
            r'withdrawal lee pmt',           # Internal loan payments
            r'co\.?gov.*csupymt',            # CSU tuition payments
            r'cogov.*csupymt',               # CSU tuition payments (alternate format)
            r'fid bkg svc',                  # Fidelity investment transfers
            r'moneyline',                    # Investment transfers
        ]

        # Patterns for category inference (used for uncategorized transactions).
        # Descriptions are normalized before matching, so separators such as
        # "BIBLE-PROJ*" and "DR-FIELDS" are treated like spaces.
        self.category_inference_patterns = {
            'Food & Dining': [
                r'wholefds', r'whole foods', r'king soopers', r'natural grocers',
                r'trader joe', r'safeway', r'kroger', r'aldi', r'hy[- ]vee',
                r'publix', r'wegmans', r'sprouts', r'lucky[\' ]s market', r'bakers',
                r'costco(?!.*gas)', r'walmart(?!.*gas)', r'target(?!.*gas)',
                r'restaurant', r'cafe', r'coffee', r'starbucks', r'panera',
                r'chipotle', r'qdoba', r'subway', r'mcdonalds', r'burger king',
                r'taco bell', r'pizza', r'bar & grill', r'tokyo ?joe',
                r'panda express', r'noodles', r'snooze', r'fazoli', r'baileys',
                r'scooter.*coffee', r'matador mexican'
            ],
            'Transportation': [
                r'cenex', r'shell', r'conoco', r'phillips 66', r'circle k',
                r'kwik stop', r'maverik', r'amoco', r'bp\s', r'costco gas',
                r'fuel', r'sapp bros', r'mega saver', r'kum.*go',
                r'auto', r'tire', r'oil change', r'car wash', r'mechanic',
                r'discount.*tire', r'grease monkey', r'jiffy lube',
                r'o\'reilly', r'autozone', r'napa'
            ],
            'Personal & Household': [
                r'amazon', r'best buy', r'barnes.*noble', r'old navy',
                r'hollister', r'eddie bauer', r'rei\.com', r'rei #',
                r'apple store', r'michaels', r'hobby lobby',
                r'salon', r'spa', r'barber', r'hair', r'aveda',
                r'fitness', r'gym', r'clothing', r'shoe', r'beauty',
                r'sally beauty', r'usps', r'fedex', r'ups',
                r'zoom\.com', r'wix\.com', r'ubindi', r'tello'
            ],
            'Health & Wellness': [
                r'pharmacy', r'walgreens', r'cvs', r'medical', r'dental',
                r'doctor', r'clinic', r'hospital', r'health', r'wellness',
                r'methodist', r'uchealth', r'dr[- ]fields', r'petco', r'petsmart',
                r'pet supplies', r'veterinar', r'vet clinic'
            ],
            'Housing & Utilities': [
                r'home depot', r'lowes', r'ace hardware', r'menards',
                r'home improvement', r'hardware', r'garden center',
                r'irrigation', r'carpet', r'homegoods', r'bed bath',
                r'xcel energy', r'fortcolutilities', r'connexion',
                r'electric', r'gas company', r'water', r'sewer', r'trash',
                r'internet', r'phone', r'cable', r'republic services',
                r'utility', r'landfill', r'farmers ins', r'insurance',
                r'irs.*usataxpymt', r'irs.*tax'
            ],
            'Travel & Entertainment': [
                r'disney', r'netflix', r'spotify', r'theater', r'movie',
                r'prime video', r'streaming', r'hulu', r'hbo'
            ],
            'Giving': [
                r'council tree cov', r'council tree covenant',
                r'serve ?6\.?8', r'serve6', r'serve 6',
                r'bible[- ]?(?:project|proj)', r'bibleproject',
                r'boys.*girls.*club', r'bgc', r'cure international', r'cure\.org',
                r'church', r'ministry', r'ministries', r'salvation army',
                r'red cross', r'united way', r'habitat.*humanity', r'goodwill',
                r'charity', r'donate', r'donation', r'tithe', r'offering',
                r'compassion', r'world vision', r'samaritan', r'food bank',
                r'rescue mission'
            ],
        }

        # Check amount patterns for inference (amount -> likely category)
        self.check_amount_patterns = [
            # (min_amount, max_amount, category, description_pattern)
            # Add patterns as needed based on your check writing habits
        ]

        # These specific merchants override broad bank labels such as
        # "Merchandise", which would otherwise prevent description inference.
        self.merchant_category_overrides = {
            'Personal & Household': [r'ubindi'],
            'Health & Wellness': [r'dr[- ]fields'],
            'Giving': [r'bible[- ]?(?:project|proj)'],
        }

    def connect_db(self):
        """Create database connection and tables"""
        self.conn = sqlite3.connect(self.db_path)
        self.create_tables()

    def create_tables(self):
        """Create the transactions table with the canonical posted-date schema."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_date DATE NOT NULL,
                year INTEGER NOT NULL,
                description TEXT NOT NULL,
                category TEXT,
                amount DECIMAL(10,2) NOT NULL,
                retirement BOOLEAN NOT NULL,
                account TEXT NOT NULL,
                check_number TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transaction_date
            ON transactions(transaction_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_year
            ON transactions(year)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_category
            ON transactions(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_retirement
            ON transactions(retirement)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_account
            ON transactions(account)
        """)

        self.conn.commit()

    def normalize_description(self, description: str) -> str:
        """Normalize merchant text so punctuation and separators do not break rules."""
        if not description:
            return ""

        normalized = str(description).casefold()
        normalized = re.sub(r'[-_/*]+', ' ', normalized)
        return re.sub(r'\s+', ' ', normalized).strip()

    def matches_patterns(self, description: str, patterns: List[str]) -> bool:
        """Return whether normalized merchant text matches any configured pattern."""
        normalized = self.normalize_description(description)
        return any(re.search(pattern, normalized) for pattern in patterns)

    def is_grocery_store(self, description: str) -> bool:
        """Check if description matches a grocery store."""
        return self.matches_patterns(description, self.grocery_store_patterns)

    def is_credit_card_payment(self, description: str) -> bool:
        """Check if transaction is a credit card payment"""
        return self.matches_patterns(description, self.credit_card_payment_patterns)

    def should_exclude_checking_transaction(self, description: str) -> bool:
        """Check if checking transaction should be excluded (transfers, investments, tuition)"""
        return self.matches_patterns(description, self.checking_exclusion_patterns)

    def map_category(self, category: str, description: str = "") -> str:
        """Map incoming category to our standard categories"""
        category_lower = str(category or '').strip().casefold()
        if category_lower in ['', 'nan', 'none']:
            return self.infer_category(description)

        # Specific merchant rules take precedence over broad source labels.
        for mapped_category, patterns in self.merchant_category_overrides.items():
            if self.matches_patterns(description, patterns):
                return mapped_category

        # The reduced taxonomy intentionally combines groceries and dining.
        if category_lower in ['food & drink', 'food & dining', 'food']:
            return 'Food & Dining'

        # Look up in mapping
        if category_lower in self.category_mapping:
            return self.category_mapping[category_lower]

        # Check if it already matches a standard category (case-insensitive)
        for std_category in self.categories.keys():
            if category_lower == std_category.casefold():
                return std_category

        # Fall back to inference
        inferred = self.infer_category(description)
        if inferred != 'Personal & Household':
            return inferred

        return 'Personal & Household'

    def infer_category(self, description: str) -> str:
        """Infer category from transaction description"""
        if not description:
            return 'Personal & Household'

        normalized_description = self.normalize_description(description)

        for category, patterns in self.category_inference_patterns.items():
            for pattern in patterns:
                if re.search(pattern, normalized_description):
                    return category

        return 'Personal & Household'

    def get_retirement_flag(self, category: str) -> bool:
        """Get retirement flag for a category"""
        return self.categories.get(category, False)

    def clean_description(self, description: str) -> str:
        """Clean up transaction description"""
        if not description:
            return ""
        
        # Remove common prefixes
        prefixes_to_remove = [
            'Ext Credit Card Debit ',
            'Ext Credit Card Credit ',
            'Ext Debit Card ',
            'ACH Debit ',
            'ACH Deposit ',
            'POS Transaction ',
        ]
        
        result = str(description).strip()
        for prefix in prefixes_to_remove:
            if result.startswith(prefix):
                result = result[len(prefix):].strip()
        
        # Remove trailing location info pattern (city/state)
        result = re.sub(r'\s+[A-Z]{2}US$', '', result)
        result = re.sub(r'\s+[A-Z]{2}$', '', result)
        
        return result.strip()

    @staticmethod
    def _is_blank(value) -> bool:
        """Handle pandas missing values and blank strings consistently."""
        if value is None:
            return True
        try:
            if pd.isna(value):
                return True
        except (TypeError, ValueError):
            pass
        return str(value).strip().casefold() in {'', 'nan', 'nat', 'none'}

    def _record_validation_error(self, file_path: str, row_number: Optional[int], message: str):
        """Record and display an input problem without stopping the full import."""
        location = str(file_path)
        if row_number is not None:
            location += f":row {row_number}"
        full_message = f"{location}: {message}"
        self.validation_errors.append(full_message)
        print(f"  Warning: {full_message}")

    def _read_csv(self, file_path: str, required_columns: List[str]):
        """Read a CSV and validate that the expected columns are present."""
        try:
            df = pd.read_csv(file_path)
        except Exception as exc:
            raise InputValidationError(f"could not read CSV ({exc})") from exc

        # Trim a BOM/whitespace and accept case differences in bank headers.
        df.columns = [str(column).strip() for column in df.columns]
        column_lookup = {column.casefold(): column for column in df.columns}
        missing = [
            column for column in required_columns
            if column.casefold() not in column_lookup
        ]
        if missing:
            raise InputValidationError(
                f"missing required column(s): {', '.join(missing)}; "
                f"found {list(df.columns)}"
            )

        rename_map = {
            column_lookup[column.casefold()]: column
            for column in required_columns
            if column.casefold() in column_lookup
        }
        return df.rename(columns=rename_map)

    def _validate_rows(
        self,
        df,
        file_path: str,
        date_column: str,
        amount_columns: List[str],
    ):
        """Keep valid rows and report malformed dates, descriptions, or amounts."""
        valid_indices = []
        for row_number, (index, row) in enumerate(df.iterrows(), start=2):
            errors = []

            date_value = row.get(date_column)
            if self._is_blank(date_value):
                errors.append(f"missing {date_column}")
            else:
                try:
                    pd.to_datetime(date_value, errors='raise')
                except (TypeError, ValueError):
                    errors.append(f"invalid {date_column}: {date_value!r}")

            if self._is_blank(row.get('Description')):
                errors.append('missing Description')

            populated_amounts = []
            for amount_column in amount_columns:
                value = row.get(amount_column)
                if self._is_blank(value):
                    continue
                populated_amounts.append(amount_column)
                try:
                    amount = float(str(value).replace(',', '').strip())
                    if not math.isfinite(amount):
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"invalid {amount_column}: {value!r}")

            if not populated_amounts:
                errors.append(f"missing amount ({'/'.join(amount_columns)})")

            if errors:
                self._record_validation_error(file_path, row_number, '; '.join(errors))
            else:
                valid_indices.append(index)

        return df.loc[valid_indices].copy()

    def _read_and_validate_csv(
        self,
        file_path: str,
        required_columns: List[str],
        date_column: str,
        amount_columns: List[str],
    ):
        df = self._read_csv(file_path, required_columns)
        return self._validate_rows(df, file_path, date_column, amount_columns)

    def process_chase_csv(self, file_path: str) -> List[Tuple]:
        """Process Chase CSV file and return transaction records"""
        print(f"Processing Chase CSV: {file_path}")

        df = self._read_and_validate_csv(
            file_path,
            ['Post Date', 'Type', 'Amount', 'Description', 'Category'],
            'Post Date',
            ['Amount'],
        )
        transactions = []

        for _, row in df.iterrows():
            # Skip payments, returns, adjustments
            transaction_type = str(row['Type']).strip().lower()
            if transaction_type in ['payment', 'return', 'adjustment']:
                continue

            # Skip positive amounts (credits)
            amount = float(row['Amount'])
            if amount > 0:
                continue

            amount = abs(amount)

            # Use the posted date consistently across all account formats.
            transaction_date = pd.to_datetime(row['Post Date']).date()
            year = transaction_date.year

            # Get and clean description
            description = self.clean_description(str(row['Description']))

            # Get and map category
            raw_category = str(row['Category']).strip() if pd.notna(row['Category']) else ''
            category = self.map_category(raw_category, description)

            # Get retirement flag
            retirement = self.get_retirement_flag(category)

            transactions.append((
                transaction_date,
                year,
                description,
                category,
                amount,
                retirement,
                'Chase',
                None  # check_number
            ))

        print(f"  Processed {len(transactions)} transactions")
        return transactions

    def process_firsttech_mastercard_csv(self, file_path: str) -> List[Tuple]:
        """Process FirstTech MasterCard CSV file"""
        print(f"Processing FirstTech MasterCard CSV: {file_path}")

        df = self._read_and_validate_csv(
            file_path,
            ['Posting Date', 'Transaction Type', 'Amount', 'Description', 'Transaction Category'],
            'Posting Date',
            ['Amount'],
        )
        transactions = []

        for _, row in df.iterrows():
            transaction_type = str(row['Transaction Type']).strip().casefold()

            # Skip credits (payments)
            if transaction_type == 'credit':
                continue

            # Skip positive amounts
            amount = float(row['Amount'])
            if amount > 0:
                continue

            amount = abs(amount)

            # Parse date and extract year
            transaction_date = pd.to_datetime(row['Posting Date']).date()
            year = transaction_date.year

            # Get description - prefer Extended Description
            if pd.notna(row.get('Extended Description')) and row['Extended Description']:
                description = str(row['Extended Description']).strip()
            else:
                description = str(row['Description']).strip()

            description = self.clean_description(description)

            # Get and map category
            raw_category = str(row['Transaction Category']).strip() if pd.notna(row.get('Transaction Category')) else ''
            category = self.map_category(raw_category, description)

            retirement = self.get_retirement_flag(category)

            transactions.append((
                transaction_date,
                year,
                description,
                category,
                amount,
                retirement,
                'FirstTech_MC',
                None
            ))

        print(f"  Processed {len(transactions)} transactions")
        return transactions

    def process_capitalone_csv(self, file_path: str) -> List[Tuple]:
        """Process Capital One (REI) CSV file"""
        print(f"Processing Capital One CSV: {file_path}")

        df = self._read_and_validate_csv(
            file_path,
            ['Posted Date', 'Description', 'Category', 'Debit', 'Credit'],
            'Posted Date',
            ['Debit', 'Credit'],
        )
        transactions = []

        for _, row in df.iterrows():
            # Skip credits (payments)
            if pd.notna(row['Credit']) and float(row['Credit']) > 0:
                continue

            # Skip rows without a debit amount
            if pd.isna(row['Debit']) or float(row['Debit']) == 0:
                continue

            amount = float(row['Debit'])

            # Use the posted date consistently across all account formats.
            transaction_date = pd.to_datetime(row['Posted Date']).date()
            year = transaction_date.year

            description = self.clean_description(str(row['Description']))

            raw_category = str(row['Category']).strip() if pd.notna(row['Category']) else ''
            category = self.map_category(raw_category, description)

            retirement = self.get_retirement_flag(category)

            transactions.append((
                transaction_date,
                year,
                description,
                category,
                amount,
                retirement,
                'CapitalOne_REI',
                None
            ))

        print(f"  Processed {len(transactions)} transactions")
        return transactions

    def process_firsttech_checking_csv(self, file_path: str) -> List[Tuple]:
        """Process FirstTech Checking CSV file - only Debits and Checks"""
        print(f"Processing FirstTech Checking CSV: {file_path}")

        df = self._read_and_validate_csv(
            file_path,
            ['Posting Date', 'Transaction Type', 'Amount', 'Description', 'Transaction Category'],
            'Posting Date',
            ['Amount'],
        )
        transactions = []

        for _, row in df.iterrows():
            transaction_type = str(row['Transaction Type']).strip()

            # Only process Debit and Check transactions
            if transaction_type not in ['debit', 'check']:
                continue

            # Get description for filtering
            if pd.notna(row.get('Extended Description')) and row['Extended Description']:
                description = str(row['Extended Description']).strip()
            else:
                description = str(row['Description']).strip()

            # Skip credit card payments
            if self.is_credit_card_payment(description):
                continue

            # Skip excluded transactions (transfers, investments, tuition)
            if self.should_exclude_checking_transaction(description):
                continue

            # Skip transfers
            type_field = str(row.get('Type', '')).lower()
            if 'transfer' in type_field or 'withdrawal' in type_field:
                # But allow if it's a specific bill payment (not internal transfer)
                if 'transfer to' in description.lower() or 'transfer from' in description.lower():
                    continue

            amount = float(row['Amount'])
            if amount > 0:
                continue

            amount = abs(amount)

            # Parse date
            transaction_date = pd.to_datetime(row['Posting Date']).date()
            year = transaction_date.year

            description = self.clean_description(description)

            # Handle check number
            check_number = None
            if transaction_type == 'check':
                check_num_raw = row.get('Check Number', '')
                if not self._is_blank(check_num_raw):
                    try:
                        parsed_check_number = float(str(check_num_raw).strip())
                        if not math.isfinite(parsed_check_number) or not parsed_check_number.is_integer():
                            raise ValueError
                        check_number = str(int(parsed_check_number))
                    except (TypeError, ValueError):
                        self._record_validation_error(
                            file_path,
                            None,
                            f"invalid Check Number: {check_num_raw!r}",
                        )
                        continue

            # Get category - for checks, try inference first
            raw_category = str(row.get('Transaction Category', '')).strip() if pd.notna(row.get('Transaction Category')) else ''
            
            if transaction_type == 'check' and (not raw_category or raw_category.casefold() in ['', 'nan', 'none']):
                # Try to infer from description or amount patterns
                category = self.infer_category(description)
            else:
                category = self.map_category(raw_category, description)

            retirement = self.get_retirement_flag(category)

            transactions.append((
                transaction_date,
                year,
                description,
                category,
                amount,
                retirement,
                'FirstTech_Checking',
                check_number
            ))

        print(f"  Processed {len(transactions)} transactions")
        return transactions

    def insert_transactions(self, transactions: List[Tuple]):
        """Insert transactions into database"""
        if not transactions:
            return

        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO transactions
            (transaction_date, year, description, category, amount, retirement, account, check_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, transactions)

        self.conn.commit()
        print(f"  Inserted {len(transactions)} transactions")

    def process_csv_file(self, file_path: str) -> List[Tuple]:
        """Route CSV file to appropriate processor based on filename/format"""
        filename = os.path.basename(file_path).lower()

        # Read a sample to help identify format. A malformed file should not
        # prevent valid files in the same directory from being imported.
        try:
            df_sample = pd.read_csv(file_path, nrows=3)
        except Exception as exc:
            self._record_validation_error(file_path, None, f"could not read CSV ({exc})")
            return []
        columns = [str(col).strip().casefold() for col in df_sample.columns]

        if 'firsttechchecking' in filename or 'ftchecking' in filename:
            return self.process_firsttech_checking_csv(file_path)
        elif 'firsttechmastercard' in filename or 'ftmastercard' in filename or 'ftcreditcard' in filename:
            return self.process_firsttech_mastercard_csv(file_path)
        elif 'chase' in filename:
            return self.process_chase_csv(file_path)
        elif 'capitalone' in filename or 'rei' in filename:
            return self.process_capitalone_csv(file_path)
        elif 'posting date' in columns and 'transaction category' in columns:
            # FirstTech format - determine by filename or content
            if 'checking' in filename:
                return self.process_firsttech_checking_csv(file_path)
            else:
                return self.process_firsttech_mastercard_csv(file_path)
        elif 'post date' in columns and 'type' in columns:
            return self.process_chase_csv(file_path)
        elif 'posted date' in columns and 'card no.' in columns:
            return self.process_capitalone_csv(file_path)
        else:
            print(f"Unknown CSV format: {file_path}")
            print(f"Columns: {list(df_sample.columns)}")
            return []

    def import_all_csvs(self, directory: str = "."):
        """Import all CSV files from directory"""
        self.connect_db()

        # Find all CSV files
        csv_patterns = [
            os.path.join(directory, "*.csv"),
            os.path.join(directory, "*.CSV"),
        ]

        csv_files = []
        for pattern in csv_patterns:
            csv_files.extend(glob.glob(pattern))

        # Remove duplicates (case-insensitive on Windows)
        seen = set()
        unique_files = []
        for f in csv_files:
            f_lower = f.lower()
            if f_lower not in seen:
                seen.add(f_lower)
                unique_files.append(f)

        csv_files = unique_files

        if not csv_files:
            print(f"No CSV files found in {directory}")
            return

        print(f"\nFound {len(csv_files)} CSV files to process:\n")

        total_transactions = 0
        for file_path in sorted(csv_files):
            try:
                transactions = self.process_csv_file(file_path)
            except InputValidationError as exc:
                self._record_validation_error(file_path, None, str(exc))
                continue
            if transactions:
                self.insert_transactions(transactions)
                total_transactions += len(transactions)

        print(f"\n{'='*60}")
        print(f"IMPORT COMPLETE: {total_transactions} total transactions")
        print(f"{'='*60}")

        if self.validation_errors:
            print(f"Skipped {len(self.validation_errors)} invalid input row/file issue(s)")

        self.generate_summary()

    def generate_summary(self):
        """Generate import summary report"""
        cursor = self.conn.cursor()

        print("\n" + "="*60)
        print("SPENDTRAX IMPORT SUMMARY")
        print("="*60)

        # Total by year
        print("\nBy Year:")
        cursor.execute("""
            SELECT year, COUNT(*), SUM(amount)
            FROM transactions
            GROUP BY year
            ORDER BY year
        """)
        for year, count, amount in cursor.fetchall():
            print(f"  {year}: {count:,} transactions, ${amount:,.2f}")

        # By account
        print("\nBy Account:")
        cursor.execute("""
            SELECT account, COUNT(*), SUM(amount)
            FROM transactions
            GROUP BY account
            ORDER BY account
        """)
        for account, count, amount in cursor.fetchall():
            print(f"  {account}: {count:,} transactions, ${amount:,.2f}")

        # By category
        print("\nBy Category:")
        cursor.execute("""
            SELECT category, COUNT(*), SUM(amount)
            FROM transactions
            GROUP BY category
            ORDER BY SUM(amount) DESC
        """)
        for category, count, amount in cursor.fetchall():
            print(f"  {category}: {count:,} transactions, ${amount:,.2f}")

        # Retirement breakdown
        print("\nRetirement Breakdown:")
        cursor.execute("""
            SELECT retirement, COUNT(*), SUM(amount)
            FROM transactions
            GROUP BY retirement
        """)
        for retirement, count, amount in cursor.fetchall():
            label = "Retirement" if retirement else "Non-Retirement"
            print(f"  {label}: {count:,} transactions, ${amount:,.2f}")

        # Checks summary
        cursor.execute("""
            SELECT COUNT(*), SUM(amount)
            FROM transactions
            WHERE check_number IS NOT NULL
        """)
        check_count, check_amount = cursor.fetchone()
        if check_count and check_count > 0:
            print(f"\nChecks: {check_count:,} transactions, ${check_amount:,.2f}")

        # Date range
        cursor.execute("SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions")
        min_date, max_date = cursor.fetchone()
        print(f"\nDate Range: {min_date} to {max_date}")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='SpendTrax CSV Importer')
    parser.add_argument('--dir', '-d', default='.', help='Directory containing CSV files')
    parser.add_argument('--db', default='spendtrax.db', help='Database file path')
    parser.add_argument('--fresh', action='store_true', help='Delete existing database and start fresh')

    args = parser.parse_args()

    print("SpendTrax 2.0 - CSV to SQLite Importer")
    print("="*60)

    # Initialize importer
    importer = SpendTraxImporter(db_path=args.db)

    # Delete existing database if fresh start requested
    if args.fresh and os.path.exists(args.db):
        print(f"Removing existing database: {args.db}")
        os.remove(args.db)

    try:
        importer.import_all_csvs(args.dir)
        print(f"\nDatabase created: {args.db}")
    except Exception as e:
        print(f"Error during import: {e}")
        import traceback
        traceback.print_exc()
    finally:
        importer.close()


if __name__ == "__main__":
    main()
