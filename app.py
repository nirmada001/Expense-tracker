import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, firestore
import pyrebase
from datetime import datetime
import pytz
import matplotlib
matplotlib.use('Agg')  # Use Agg backend for non-GUI environments
from matplotlib.figure import Figure
import io
from flask import Response

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Load environment variables from .env
load_dotenv()

# Firebase Admin SDK setup with environment variables
firebase_credentials = credentials.Certificate({
    "type": "service_account",
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
})
firebase_admin.initialize_app(firebase_credentials)

# Initialize Firestore
db = firestore.client()

# Firebase Pyrebase setup with environment variables
firebase_config = {
    "apiKey": os.getenv("FIREBASE_API_KEY"),
    "authDomain": f"{os.getenv('FIREBASE_PROJECT_ID')}.firebaseapp.com",
    "databaseURL": f"https://{os.getenv('FIREBASE_PROJECT_ID')}-default-rtdb.firebaseio.com",
    "projectId": os.getenv("FIREBASE_PROJECT_ID"),
    "storageBucket": f"{os.getenv('FIREBASE_PROJECT_ID')}.appspot.com",
}
firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()


@app.route('/')
def index():
    return render_template('index.html')


# register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    error_message = None
    success_message = None

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # check if username is already taken
        users_ref = db.collection('users')
        username_query = users_ref.where('username', '==', username).get()

        # display error message
        if username_query:
            error_message = "Username already taken"
        elif len(password) < 6:
            error_message = "Password should be at least 6 characters long."
        else:
            try:
                user = auth.create_user_with_email_and_password(email, password)
                uid = user['localId']

                #save the username and email in firebase collection
                db.collection('users').document(uid).set({
                    'username' : username,
                    'email': email
                })

                success_message = "Registration Sucessfull..Please Log in"
                return redirect(url_for('login'))
            except Exception as e:
                if "EMAIL_EXISTS" in str(e):
                    error_message = "Email is already registered."
                elif "INVALID_EMAIL" in str(e):
                    error_message = "Invalid email address."
                else:
                    error_message = f"Registration failed: {str(e)}"


    return render_template('register.html', error_message=error_message, success_message = success_message)

# login route
@app.route('/login', methods = ['GET', 'POST'])
def login():
    error_message = None

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            user = auth.sign_in_with_email_and_password(email, password)
            uid = user['localId']

            #fetch username from the firestore database
            user_doc = db.collection('users').document(uid).get()
            username = user_doc.to_dict().get('username')

            session['user'] = {'email': email, 'username':username, 'uid':uid}
            return redirect(url_for('home'))
        except Exception as e:
            error_message = "Login Failed: Invalid email or password"
    return render_template('login.html', error_message = error_message)

#home route
@app.route('/home')
def home():
    if 'user' in session:
        return render_template('home.html', username=session['user']['username'])
    else:
        flash("Please log in to access the home page.", "danger")
        return redirect(url_for('login'))
    
#add expenses route
@app.route('/addExpense', methods=['GET', 'POST'])
def addExpense():
    success_message = None

    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Use the correct key to access the user ID from the session
        user_id = session['user']['uid']
        title = request.form['title']
        amount = float(request.form['amount'])
        
        # When adding expense
        date = datetime.strptime(request.form['date'], '%Y-%m-%d')  # or use the correct format

        # Store the datetime object
        db.collection('expenses').add({
            'user_id': user_id,
            'title': title,
            'amount': amount,
            'date': date
        })

        success_message = "Expense added successfully!"
        # You can optionally redirect to another page, e.g., view expenses, after adding

    return render_template('addExpenses.html', username=session['user']['username'], success_message=success_message)

# view expenses route
@app.route('/expenses')
def view_expenses():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user']['uid']
    expenses_ref = db.collection('expenses').where('user_id', '==', user_id)
    expenses = expenses_ref.stream()
    expense_list = [{'id': exp.id, **exp.to_dict()} for exp in expenses]

    return render_template('expenses.html', expenses=expense_list)

# Route to generate the expense chart
@app.route('/expense-chart')
def expense_chart():
    user_id = session['user']['uid']
    expenses_ref = db.collection('expenses').where('user_id', '==', user_id)
    expenses = expenses_ref.stream()

    # Prepare data for plotting
    dates = []
    amounts = []
    for expense in expenses:
        data = expense.to_dict()
        if 'date' in data and 'amount' in data:
            date = data['date']
            amount = data['amount']
            if isinstance(date, str):
                date = datetime.fromisoformat(date)
            dates.append(date)
            amounts.append(amount)

    # Sort dates and amounts
    dates, amounts = zip(*sorted(zip(dates, amounts)))

    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(dates, amounts, marker='o')
    ax.set_title("Expense Trends Over Time")
    ax.set_xlabel("Date")
    ax.set_ylabel("Amount ($)")
    ax.grid(True)

    img = io.BytesIO()
    fig.savefig(img, format='png')
    img.seek(0)

    return Response(img.getvalue(), mimetype='image/png')

# delete expense route
@app.route('/delete_expense/<expense_id>', methods=['POST'])
def delete_expense(expense_id):
    success_message = None
    error_message = None

    if 'user' not in session:
        return redirect(url_for('login'))

    # Attempt to delete the specified expense document
    try:
        db.collection('expenses').document(expense_id).delete()
        success_message = "Expense deleted successfully!"
    except Exception as e:
        error_message = "Failed to delete expense"

    # Fetch updated list of expenses
    user_id = session['user']['uid']
    expenses_ref = db.collection('expenses').where('user_id', '==', user_id)
    expenses = expenses_ref.stream()
    expense_list = [{'id': exp.id, **exp.to_dict()} for exp in expenses]

    return render_template('expenses.html', expenses=expense_list, success_message=success_message, error_message=error_message)




if __name__ == '__main__':
    app.run(debug=True)