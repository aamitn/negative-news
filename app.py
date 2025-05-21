import json
import os
from curl_cffi import requests as curl_requests
import matplotlib # Required by nltk to load runtime worfreqs DONT DELETE
import nltk
nltk.download('vader_lexicon')
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import webbrowser
import tkinter as tk
from tkinter import scrolledtext, ttk, PhotoImage, messagebox
import base64
import re
from io import BytesIO
from http import HTTPStatus  
try:
    import docx
except ImportError:
    docx = None
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

os.environ['REQUESTS_CA_BUNDLE'] = 'cacert.pem'

#FALLBACK DEFAULTS if congif.json not found
GOOGLE_SEARCH_API_KEY = None
GOOGLE_SEARCH_CX = None
TOTAL_RESULTS = 10
PDF_MAX_PAGES = 5
DOCX_MAX_PARAGRAPHS = 50
MAX_CHARS = 5000
CONNECT_TIMEOUT = 5 
READ_TIMEOUT = 10
MAX_RETRIES = 3
CURL_CFFI_IMPERSONATOR = "chrome"  # Options: chrome, safari, safari_ios
NAME_MIN_LENGTH = 3

# Load configuration
try:
    with open('config.json', 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)
        
        # GET APIKEY (http://console.cloud.google.com/apis/library/customsearch.googleapis.com OR https://developers.google.com/custom-search/v1/overview)
        GOOGLE_SEARCH_API_KEY = config.get('google_search_api_key', GOOGLE_SEARCH_API_KEY)
        
        # GET CX (https://cse.google.com/all OR https://programmablesearchengine.google.com/controlpanel/all)
        GOOGLE_SEARCH_CX = config.get('google_search_cx', GOOGLE_SEARCH_CX)
        
        #Total number of google search results to fetch
        TOTAL_RESULTS = config.get('total_results', TOTAL_RESULTS)

        # Maximum number of pages to read from PDF
        PDF_MAX_PAGES = config.get('pdf_max_pages', PDF_MAX_PAGES)

        # Maximum number of paragraphs to read from DOCX
        DOCX_MAX_PARAGRAPHS = config.get('docx_max_paragraphs', DOCX_MAX_PARAGRAPHS)

        # Maximum number of characters to read from text
        MAX_CHARS = config.get('max_chars', MAX_CHARS)

        #Connection settings
        CONNECT_TIMEOUT = config.get('connection_timeout', CONNECT_TIMEOUT)
        READ_TIMEOUT = config.get('read_timeout', READ_TIMEOUT)
        MAX_RETRIES = config.get('max_retries', MAX_RETRIES)
        
        #Curl Browser impersonators: chrome, safari and safari_ios
        CURL_CFFI_IMPERSONATOR = config.get('curl_cffi_impersonator', CURL_CFFI_IMPERSONATOR) 

        # Minimum length of customer name input
        NAME_MIN_LENGTH = config.get('name_min_length', NAME_MIN_LENGTH)

except FileNotFoundError:
    messagebox.showwarning("Configuration Error", "Config file not found. Using Predefined  Defaults. Please create a config.json file in program root directory.")
except KeyError as e:
    messagebox.showwarning("Configuration Error", f"Missing configuration key in config.json: {e}")


def pretty_json(json_obj):
    return json.dumps(json_obj, indent=4)



def extract_text_from_pdf(content_bytes):
    """
    Extract text from the first `max_pages` of a PDF, up to `max_chars` characters.
    """
    if not PyPDF2:
        return ""
    reader = PyPDF2.PdfReader(BytesIO(content_bytes))
    text = ""
    for i, page in enumerate(reader.pages):
        if i >= PDF_MAX_PAGES or len(text) >= MAX_CHARS:
            break
        page_text = page.extract_text() or ""
        text += page_text
        if len(text) >= MAX_CHARS:
            text = text[:MAX_CHARS]
            break
    return text

def extract_text_from_docx(content_bytes):
    """
    Extract text from the first `max_paragraphs` of a DOCX, up to `max_chars` characters.
    """
    if not docx:
        return ""
    file_stream = BytesIO(content_bytes)
    document = docx.Document(file_stream)
    paragraphs = []
    for i, para in enumerate(document.paragraphs):
        if i >= DOCX_MAX_PARAGRAPHS or sum(len(p) for p in paragraphs) >= MAX_CHARS:
            break
        paragraphs.append(para.text)
        if sum(len(p) for p in paragraphs) >= MAX_CHARS:
            break
    text = "\n".join(paragraphs)
    return text[:MAX_CHARS]


def display_response_tree(tree, json_obj):
    tree.delete(*tree.get_children())  # Clear existing items

    def _display_tree(parent, data):
        if isinstance(data, dict):
            for key, value in data.items():
                child = tree.insert(parent, "end", text=key)
                _display_tree(child, value)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                child = tree.insert(parent, "end", text=str(index))
                _display_tree(child, item)
        else:
            tree.insert(parent, "end", text=str(data))

    _display_tree("", json_obj)


def update_textarea(textarea, message):
    textarea.insert(tk.END, message + '\n')
    textarea.see(tk.END)


def calculate_sentiment_score(text):
    sid = SentimentIntensityAnalyzer()
    sentiment_scores = sid.polarity_scores(text)

    # Adjust the compound score to represent risk
    risk_score = sentiment_scores['compound'] * -1

    return risk_score


def calculate_risk_score(sentiment_score):
    if sentiment_score > 0.3:
        return "Very High Risk"
    elif sentiment_score > 0.1:
        return "High Risk"
    elif sentiment_score > -0.1:
        return "Medium Risk"
    elif sentiment_score > -0.3:
        return "Low Risk"
    else:
        return "Very Low Risk"


def search_and_score_with_api(customer_name, languages_keywords, selected_languages, excluded_sites, num_results=TOTAL_RESULTS,
                              api_key=None, high_risk_links=None, very_high_risk_links=None):
    
    if not customer_name or not customer_name.strip() or len(customer_name.strip()) < NAME_MIN_LENGTH:
        messagebox.showwarning("Input Error", "Please enter a customer name with at least 3 characters before searching.")
        return

    # Only allow letters, numbers, and spaces
    if not re.match(r'^[\w\s]+$', customer_name.strip()):
        messagebox.showwarning("Input Error", "Customer name must not contain special characters.")
        return

    if not api_key:
        raise ValueError("API key is required to use the Custom Search API")

    for lang in selected_languages:
        keywords = languages_keywords.get(lang)
        if keywords:
            print(f"Searching in {lang} language...")

        excluded_sites_query = ' '.join([f'-site:{site}' for site in excluded_sites])
        excluded_keywords_query = ' OR '.join([f'{keyword}' for keyword in keywords])

        search_query = f'"{customer_name}" {excluded_keywords_query} {excluded_sites_query}'

        print(f"Google Search Query: {search_query}")

        search_params = {
            'cx':  GOOGLE_SEARCH_CX,
            'key': GOOGLE_SEARCH_API_KEY,
            'q': search_query,
            'num': num_results,
        }

        api_url = 'https://www.googleapis.com/customsearch/v1'

        # Use curl_cffi requests for the API call
        response = curl_requests.get(api_url, params=search_params, timeout=CONNECT_TIMEOUT + READ_TIMEOUT, impersonate=CURL_CFFI_IMPERSONATOR, verify=True)
        print(str(response.text))
        display_response_tree(json_tree, response.json())

        data = response.json()

        if 'items' in data:
            for item in data['items']:
                link = item['link']
                print(f"Currently Processesed Link: {link}")
                try:
                    # Use curl_requests for the link fetch
                    response = curl_requests.get(
                        link,
                        timeout=CONNECT_TIMEOUT + READ_TIMEOUT,
                        impersonate=CURL_CFFI_IMPERSONATOR,
                        verify=True
                    )

                    status_code = response.status_code
                    try:
                        status_text = HTTPStatus(status_code).phrase
                    except ValueError:
                        status_text = "Unknown Status Code"

                    print(f"Status Code: {status_code} - {status_text}")
                    print(f"Response Time: {response.elapsed:.2f}s")
                    update_textarea(output_textarea, f"{response.status_code}, {status_text}, {response.elapsed:.2f}s")

                    if response.status_code == 200:
                        content_type = response.headers.get('Content-Type', '')
                        link_lower = link.lower()
                        text_content = ""

                        if '.pdf' in link_lower or 'application/pdf' in content_type:
                            text_content = extract_text_from_pdf(response.content)
                        elif '.docx' in link_lower or 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type:
                            text_content = extract_text_from_docx(response.content)
                        else:
                            text_content = response.text
                        sentiment_score = calculate_sentiment_score(text_content)
                        risk_score = calculate_risk_score(sentiment_score)

                        message = (
                            f'Link: {link}\n'
                            f'Sentiment Score: {sentiment_score}\n'
                            f'Risk Score: {risk_score}\n'
                        )
                        print(message)
                        update_textarea(output_textarea, message)

                        if risk_score == "High Risk":
                            high_risk_links.append(link)
                        elif risk_score == "Very High Risk":
                            very_high_risk_links.append(link)
                    else:
                        message = f'Skipping link (HTTP {response.status_code}): {link}'
                        print(message)
                        update_textarea(output_textarea, message)

                except curl_requests.errors.RequestsError as e:
                    message = f'Skipping link (request failed): {link}\nError: {str(e)}'
                    print(message)
                    update_textarea(output_textarea, message)
                except Exception as e:
                    message = f'Skipping link (unexpected error): {link}\nError: {str(e)}'
                    print(message)
                    update_textarea(output_textarea, message)
                finally:
                    print('\n====================')
                    update_textarea(output_textarea, '\n====================')
        else:
            print('No search results found.')



if __name__ == '__main__':
    customer_name = ''

    # Load configuration from JSON file
    try:
        with open('config.json', 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
            languages_keywords = config['languages_keywords']
            selected_languages = config['default_selected_languages']
            excluded_sites = config['excluded_sites']
    except FileNotFoundError:
        print("Config file not found. Using default values.")
        languages_keywords = {
            'English': ['bribery', 'fraud', 'money laundering', 'crime', 'terrorism', 'corruption']
        }
        selected_languages = ['English']
        excluded_sites = ['facebook.*']

    high_risk_links = []
    very_high_risk_links = []
    language_checkboxes = {}

    def copy_item():
        selected_items = json_tree.selection()
        if selected_items:
            item = selected_items[0]
            text = json_tree.item(item, "text")
            window.clipboard_clear()
            window.clipboard_append(text)


    def json_tree_popup(event):
        popup_menu = tk.Menu(window, tearoff=0)
        popup_menu.add_command(label="Copy", command=copy_item)

        try:
            popup_menu.tk_popup(event.x_root, event.y_root)
        finally:
            popup_menu.grab_release()


    def command():
        customer_name = customer_name_entry.get()

        # Populate selected_languages based on checkbox states
        selected_languages = [language for language, var in language_checkboxes.items() if var.get() == 1]

        search_and_score_with_api(customer_name, languages_keywords, selected_languages, excluded_sites,
                                  api_key=GOOGLE_SEARCH_API_KEY,
                                  high_risk_links=high_risk_links,
                                  very_high_risk_links=very_high_risk_links)

        print("High Risk Links:")
        update_textarea(output_textarea, "High Risk Links:\n")
        for link in high_risk_links:
            print(link)
            update_textarea(output_textarea, link)
            webbrowser.open(link)  # Open high risk link in browser

        print("\nVery High Risk Links:")
        update_textarea(output_textarea, "Very High Risk Links:\n")
        for link in very_high_risk_links:
            print(link)
            update_textarea(output_textarea, link)
            webbrowser.open(link)  # Open very high risk link in browser

    # UI CODE
    window = tk.Tk()
    window.title("Negative News Search and Analysis")
    window.geometry("800x900")  # Set initial window size
    window.configure(bg='#f0f0f0')  # Light gray background
    
    # Style configuration
    style = ttk.Style()
    style.theme_use('clam')  # Modern looking theme
    style.configure('TButton', padding=6, relief="flat", background="#2196F3")
    style.configure('TFrame', background='#f0f0f0')
    style.configure('TLabel', background='#f0f0f0', font=('Arial', 10))
    style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
    
    # Main container
    main_frame = ttk.Frame(window, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # Header section
    header_frame = ttk.Frame(main_frame)
    header_frame.pack(fill=tk.X, pady=(0, 20))
    
    header_label = ttk.Label(header_frame, text="Customer Due Diligence Search", 
                            style='Header.TLabel')
    header_label.pack()
    
    # Input section
    input_frame = ttk.LabelFrame(main_frame, text="Search Parameters", padding="10")
    input_frame.pack(fill=tk.X, pady=(0, 10))
    
    # Customer name input
    name_frame = ttk.Frame(input_frame)
    name_frame.pack(fill=tk.X, pady=5)
    customer_name_label = ttk.Label(name_frame, text="Customer Name:")
    customer_name_label.pack(side=tk.LEFT, padx=5)
    customer_name_entry = ttk.Entry(name_frame, width=40)
    customer_name_entry.pack(side=tk.LEFT, padx=5)
    
    # Language selection frame
    lang_frame = ttk.LabelFrame(input_frame, text="Select Languages", padding="5")
    lang_frame.pack(fill=tk.X, pady=10)
    
    # Create language checkboxes in a grid
    row = 0
    col = 0
    for language in languages_keywords:
        var = tk.IntVar()
        checkbox = ttk.Checkbutton(lang_frame, text=language, variable=var)
        checkbox.grid(row=row, column=col, padx=10, pady=5, sticky='w')
        language_checkboxes[language] = var
        col += 1
        if col > 2:  # 3 checkboxes per row
            col = 0
            row += 1
    
    # Search button
    search_button = ttk.Button(input_frame, text="Search and Analyze", 
                              command=command, style='TButton')
    search_button.pack(pady=10)
    
    # Results section
    results_frame = ttk.LabelFrame(main_frame, text="Search Results", padding="10")
    results_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    
    # Create notebook for tabbed views
    notebook = ttk.Notebook(results_frame)
    notebook.pack(fill=tk.BOTH, expand=True)
    
    # Text output tab
    text_frame = ttk.Frame(notebook)
    notebook.add(text_frame, text="Analysis Results")
    
    output_textarea = scrolledtext.ScrolledText(text_frame, height=15, width=70,
                                              font=('Arial', 9))
    output_textarea.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # JSON tree tab
    tree_frame = ttk.Frame(notebook)
    notebook.add(tree_frame, text="Raw Response")
    
    json_tree = ttk.Treeview(tree_frame, height=15)
    json_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # Add scrollbar to tree
    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", 
                               command=json_tree.yview)
    tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    json_tree.configure(yscrollcommand=tree_scroll.set)
    
    # Configure columns width
    json_tree.column("#0", width=500)
    
    # Bind right-click event
    json_tree.bind("<Button-3>", lambda event: json_tree_popup(event))

        # --- Menu Bar ---
    def clear_output():
        output_textarea.delete('1.0', tk.END)

    def show_about():
        about_text = (
            "Negative News Search and Analysis Tool\n"
            "Developer: Bitmutex Technologies\n"
            "Email: support@bitmtuex.com\n"
            "Website: https://bitmtuex.com\n\n"
            "Click the links below to contact or visit website."
        )
        about_win = tk.Toplevel(window)
        about_win.title("About")
        about_win.geometry("400x200")
        tk.Label(about_win, text=about_text, justify="left").pack(padx=10, pady=10, anchor="w")
        # Mailto link
        email_link = tk.Label(about_win, text="support@bitmutex.com", fg="blue", cursor="hand2")
        email_link.pack(anchor="w", padx=20)
        email_link.bind("<Button-1>", lambda e: webbrowser.open("mailto:support@bitmutex.com"))
        # Website link
        web_link = tk.Label(about_win, text="https://bitmutex.com", fg="blue", cursor="hand2")
        web_link.pack(anchor="w", padx=20)
        web_link.bind("<Button-1>", lambda e: webbrowser.open("https://bitmutex.com"))

    def show_api_key_info():
        info = (
            "How to create Google Custom Search API Key:\n"
            "1. Go to https://console.cloud.google.com/apis/library/customsearch.googleapis.com and enable the API.\n"
            "2. Go to https://console.cloud.google.com/apis/credentials and create an API key.\n"
            "3. Go to https://cse.google.com/cse/create/new to create a Custom Search Engine (CSE).\n"
            "4. Note your API key in Step2 and CSE ID (CX) in Step3.\n\n"
            "Sample config.json:\n"
            '{\n'
            '    "google_search_api_key": "YOUR_API_KEY",\n'
            '    "google_search_cx": "YOUR_CX_ID",\n'
            '    "total_results": 10,\n'
            '    "languages_keywords": {\n'
            '        "English": ["bribery", "fraud", "money laundering"]\n'
            '    },\n'
            '    "default_selected_languages": ["English"],\n'
            '    "excluded_sites": ["facebook.*", "twitter.*"]\n'
            '}'
        )
        api_win = tk.Toplevel(window)
        api_win.title("API Key Instructions")
        api_win.geometry("600x400")
        txt = scrolledtext.ScrolledText(api_win, wrap=tk.WORD, height=20, width=70)
        txt.insert(tk.END, info)
        txt.config(state=tk.DISABLED)
        txt.pack(padx=10, pady=10)

    menubar = tk.Menu(window)
    file_menu = tk.Menu(menubar, tearoff=0)
    file_menu.add_command(label="Clear", command=clear_output)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=window.quit)
    menubar.add_cascade(label="File", menu=file_menu)

    help_menu = tk.Menu(menubar, tearoff=0)
    help_menu.add_command(label="About", command=show_about)
    help_menu.add_command(label="API Key", command=show_api_key_info)
    menubar.add_cascade(label="Help", menu=help_menu)

    window.config(menu=menubar)

    # --- Status Bar ---
    status_var = tk.StringVar()
    status_var.set("Ready")
    status_bar = ttk.Label(window, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    # --- Set custom window icon from base64 ---
    icon_base64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAAAb1BMVEVHcEwGBgYKCgoBAQEEBAQBAQEDAwMFBQUPDw8REREEBAQCAgIEBAQEBAQGBgYCAgIDAwMbGxsDAwMNDQ0FBQUJCQkMDAwBAQEHBwclJSUQEBAMDAwFBQUCAgIKCgoEBAQGBgYICAh4eHgBAQEGBgYuUwrlAAAAJXRSTlMAcAnBnNLYjSQbz8TJVWd44w/eWbqFOPNABRUwSelPfbFgAv2oR2iwcwAAAbhJREFUOMt1k9mWgyAMQFHZRUVkqaBWW///Gwe1rdKZuS/CyT0khAgAAHlWlFegBymZhORC8YRtEs81Sf1RpkZeZKCDbxaQiUklxiZo/Ioj/chEfkuMXXhnMbsAEuMvAdzwaeyC7g7mKKil6yp43mUTiMIHioDptXK3i5CzNzno/fb1Vl2FP6D4f6H/LfR9/3htW9vBin0JYdaa7EX3SynxKLFhicDuxtQ9yCdGJLHUhhqVE67zj9AOkWlghqshkEKsA52VK9hHsHy7ORpuY2exnGfsGoqe1ZniQTdYTzQVToxOKTfU10YFHQdJmFYQKCdIar3MysjhUmQWaSaGpdJ0bsFyz2SSwlfxnSjwqJSCrjY3deOKcToFKzjnNeg16Ua4KoGIgp0Kl06yWKNvQYYpeeJS8CeisGy/TuB8mBxkRCEhdajU2pyN8ksdWQK5K0hDnQ2sHtGg6ZcQA2AQmCzGFIoI6Uz/SVHuKXh8d1/P3AkS8lnd5WFsRdID5r1vGbPx38shDtVhnEVyjjbIPhp0RLFSsgumnaoLds8cJOZhcduyUaRJuG8URVjROu5DZo6jU2YLPBTZD1h3JUohc5cnAAAAAElFTkSuQmCC"  

    if icon_base64.strip():
        icon_data = base64.b64decode(icon_base64)
        icon_image = PhotoImage(data=icon_data)
        window.iconphoto(True, icon_image)


    window.lift()
    window.focus_force()

    window.mainloop()
