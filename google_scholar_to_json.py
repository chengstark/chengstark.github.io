import json
from scholarly import scholarly

def fetch_publications(scholar_user_id):
    """
    Fetches publications from Google Scholar for a given user ID.
    """
    author = scholarly.search_author_id(scholar_user_id)
    scholarly.fill(author)
    
    publications = []
    for pub in author["publications"]:
        scholarly.fill(pub)  # Get detailed publication information
        publications.append({
            "name": pub["bib"]["title"],
            "publisher": pub["bib"].get("venue", "Unknown"),  # Use venue as publisher
            "releaseDate": pub["bib"].get("pub_year", "Unknown"),
            "url": pub.get("pub_url", ""),
            "summary": pub.get("abstract", "No abstract available")
        })
    return publications

def populate_json_with_publications(user_id, json_template_path, output_path):
    """
    Populates a JSON template with publications fetched from Google Scholar.
    """
    # Load the existing JSON template
    with open(json_template_path, 'r') as file:
        data = json.load(file)
    
    # Fetch publications
    publications = fetch_publications(user_id)
    
    # Add publications to the JSON
    data["publications"] = publications
    
    # Save the updated JSON
    with open(output_path, 'w') as file:
        json.dump(data, file, indent=4)

    print(f"Updated JSON saved to {output_path}")

# Replace with your Google Scholar user ID
SCHOLAR_USER_ID = "3J683FMAAAAJ"
JSON_TEMPLATE_PATH = "/Users/starkguo/Documents/chengstark.github.io/assets/json/resume.json"
OUTPUT_PATH = "/Users/starkguo/Documents/chengstark.github.io/assets/json/resume_updated.json"

# Fetch and update JSON
populate_json_with_publications(SCHOLAR_USER_ID, JSON_TEMPLATE_PATH, OUTPUT_PATH)
