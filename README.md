# FullStock: Intelligent Inventory Management

COLLABORATOR: cuteszme
CHECK-OUT OUR DEPLOYED APPLICATION IN RENDER: https://fullstock-l1pv.onrender.com/

FullStock is a modern, web-based Inventory Management and Demand Forecasting System. Built with Python and Flask, it transitions businesses from reactive stock tracking to **proactive inventory intelligence** using data analytics and predictive machine learning.

![FullStock Dashboard](https://img.shields.io/badge/Status-Production_Ready-brightgreen)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Flask](https://img.shields.io/badge/Flask-Web_Framework-black)

## 🎯 Core Features

*   **Smart Inventory Alerts**: Calculates Reorder Point (ROP) and Economic Order Quantity (EOQ) for every product.
*   **Quick Action Restocking**: Integrated UI buttons to instantly restock the optimal EOQ amount with a single click.
*   **Machine Learning Forecasting**: Powered by `scikit-learn` to predict future demand based on historical sales and seasonality.
*   **Comprehensive Audit Trail**: Immutable logging of all system actions (sales, restocking, creation) for total accountability.
*   **Multi-Store Architecture**: Manage inventory across multiple geographic locations from a single unified dashboard.
*   **Sleek Dark Mode**: Includes a custom, smart CSS-inversion Dark Mode toggle.

## 🛠️ Technology Stack

*   **Backend:** Python 3, Flask
*   **Database:** MySQL (PyMySQL, SQLAlchemy)
*   **Authentication:** Google OAuth 2.0 (Authlib)
*   **Security:** Flask-Talisman (HTTPS, CSP, CSRF protection)
*   **Data Science:** Pandas, Scikit-learn
*   **Frontend:** Vanilla HTML/JS, Tailwind CSS, Chart.js

## 🚀 Getting Started

### Local Development

1. Clone the repository
2. Set up a Python virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure Environment Variables. Create a `.env` file with:
   ```env
   SECRET_KEY=your_secret_key
   DATABASE_URL=sqlite:///data/local.db  # Or your MySQL connection string
   GOOGLE_CLIENT_ID=your_google_id
   GOOGLE_CLIENT_SECRET=your_google_secret
   ```
5. Run the application:
   ```bash
   flask run
   ```

### Docker Deployment

To run the application using Docker Compose with an isolated database:

1. Configure your `.env.docker` file.
2. Run the build command:
   ```bash
   docker-compose up --build -d
   ```

## 🔒 Security Requirements for Production
When deploying to a production environment (such as Render or AWS), ensure you set `FORCE_HTTPS=1` in your environment variables. This strictly enforces secure session cookies and prevents cross-site tracking issues during the Google OAuth handoff.
