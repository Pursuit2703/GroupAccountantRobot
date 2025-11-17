WIZARD_CONFIGS = {
    'expense': {
        'title': "➕ New Expense",
        'total_steps': 5,
        'review_step': 5,
        'steps': {
            1: {
                'instruction': "Enter the total amount.",
                'buttons': None,
                'summary': None,
            },
            2: {
                'instruction': "Send one or more receipts (images or PDFs).",
                'buttons': 'generate_expense_step_2_buttons',
                'summary': None,
            },
            3: {
                'instruction': "Add a description or category.",
                'buttons': 'generate_expense_step_3_buttons',
                'summary': None,
            },
            4: {
                'instruction': "Select who you should split the bill with.",
                'buttons': 'generate_expense_step_4_buttons',
                'summary': None,
            },
            5: {
                'instruction': "Review the details below.",
                'buttons': 'generate_expense_step_5_buttons',
                'summary': None,
            },
        }
    },
    'settlement': {
        'title': "💸 Settle Debt",
        'total_steps': 4,
        'review_step': 4,
        'steps': {
            1: {
                'instruction': "Please select the person you paid.",
                'buttons': 'generate_settlement_step_1_buttons',
                'summary': None,
            },
            2: {
                'instruction': "Your current debt to {payee_name} is <b>{total_debt_str}</b>.\nEnter the exact amount you paid.",
                'buttons': 'generate_settlement_step_2_buttons',
                'summary': None,
            },
            3: {
                'instruction': "Please upload proof of payment (e.g., a screenshot).",
                'buttons': 'generate_settlement_step_3_buttons',
                'summary': None,
            },
            4: {
                'instruction': "Everything look correct? You can still go back or edit details.",
                'buttons': 'generate_settlement_step_4_buttons',
                'summary': None,
            },
        }
    },
    'clear_debt': {
        'title': "💸 Clear Debt",
        'total_steps': 2,
        'steps': {
            1: {
                'instruction': "The total debt is <b>{total_debt_str}</b>.\n\nPlease enter the amount you want to clear.",
                'buttons': 'generate_clear_debt_step_1_buttons',
                'summary': None,
            },
            2: {
                'instruction': "You are about to clear {amount_text} from {debtor_name}.\n\nAre you sure?",
                'buttons': 'generate_clear_debt_step_2_buttons',
                'summary': None,
            },
        }
    }
}
