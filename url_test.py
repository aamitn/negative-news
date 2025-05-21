from curl_cffi import requests

# Define the URL and headers
url = 'https://www.reuters.com'

try:
    # Make the GET request using curl_cffi's requests-like interface
    # The 'impersonate' parameter can be useful to mimic real browser behavior,
    # but for a basic GET with a User-Agent, it might not be strictly necessary
    # unless you encounter issues. Here we'll just use the basic get.
    response = requests.get(url, impersonate="chrome")

    # Print the response text and status code 
    print(f"Response Text:{response.text}")
    print(f"Status Code: {response.status_code}")

except Exception as e:
    print(f"An error occurred: {e}")

