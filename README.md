# SNO Hiring Cost Tracker

A web-based tool for channel owners to submit weekly hiring/cost data, with auto-generated reports showing WoW comparison, CPFOD analysis, and Plan vs Expected metrics.

## Quick Start (Run Locally)

### Step 1: Set up the environment

```bash
cd sno-hiring-tracker
pip install -r requirements.txt
```

### Step 2: Initialize database and create users

```bash
python seed_users.py
```

### Step 3: Start the app

```bash
streamlit run app.py
```

The app will open at **http://localhost:8501**

---

## Login Credentials

| Role | Username | Password |
|------|----------|----------|
| **Admin** | Tulika | `admin123` |
| Channel 1 | SOC Channel | `soc123` |
| Channel 2 | SNO Channel | `sno123` |
| Channel 3 | Agency Channel | `agency123` |
| Channel 4 | Google Channel | `google123` |
| Channel 5 | Referral Channel | `ref123` |
| Channel 6 | FR Channel | `fr123` |

**Admin can add more users via the "Manage Users" tab in the dashboard.**

---

## Features

1. **Channel Owner Submission** — Enter weekly data via a structured form
2. **WoW Summary** — Week-over-week comparison with delta and % change
3. **CPFOD/CPO Analysis** — Channel-wise cost per first order delivery breakdown
4. **Plan vs Expected** — Set targets and compare actuals
5. **Excel Export** — Download consolidated data as .xlsx
6. **Trend Charts** — Visualize cost and CPFOD trends over time

---

## File Structure

```
sno-hiring-tracker/
├── app.py              # Main Streamlit application
├── seed_users.py       # Script to create users and initialize DB
├── requirements.txt    # Python dependencies
├── sno_hiring.db       # SQLite database (created automatically)
└── README.md           # This file
```

---

## How to Use

### For Channel Owners:
1. Go to the app URL
2. Enter your name and passcode
3. Fill in your weekly numbers in the form
4. Click "Submit Data"
5. View your past submissions in the collapsible section

### For Admin (You):
1. Log in as **Tulika** with `admin123`
2. **View Submissions** — See all channel data for any week
3. **WoW Summary** — Compare current vs previous week
4. **CPFOD Analysis** — See which channels have increasing/decreasing cost efficiency
5. **Targets** — Set Plan and Expected values for each week
6. **Manage Users** — Add new channel owners or change passcodes
7. **Export** — Download Excel for offline analysis

---

## Deploying to the Web (Optional)

Want to access this from anywhere? You can deploy for free:

### Option A: Streamlit Community Cloud (Easiest)
1. Push these files to a GitHub repo
2. Go to https://share.streamlit.io
3. Connect your GitHub and deploy

### Option B: Run on a server
```bash
# On your server
nohup streamlit run app.py --server.port 8501 --server.headless true &
```

---

## Support

If you need changes — new metrics, different report formats, more users — just ask!

---
*Built with Streamlit, SQLite, Plotly, and Pandas*