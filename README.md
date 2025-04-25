# MonoMonitor
Automatically fetch incoming transactions from your Monobank account and forward them to your email via a secure SMTP connection.

# 📬 Monobank Transactions to Email

This script retrieves your transactions from the [Monobank API](https://api.monobank.ua/) and sends them to the specified email address. It is ideal for freelancers, accountants, or anyone who wants to keep track of their spending.

---

## ⚙️ Prerequisites

- A [Monobank API token](https://api.monobank.ua/)
- SMTP configuration details (for example, from Gmail or another email provider)
- Python 3.8+
- Optionally, a cron job or another task scheduler for periodic execution

---

## 📦 Installation

Clone the repository and set up the virtual environment:

```bash
git clone https://github.com/your-username/MonoMonitor.git
cd MonoMonitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```


🧪 Configuration
Create a .env file based on the provided .env.example:


---

Feel free to modify any section to suit your needs, including adjusting paths, schedules, or other settings.
