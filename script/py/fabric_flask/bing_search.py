import json
import requests
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from datetime import datetime
import os

from openai import OpenAI

class ThesisTopicGenerator:
    def __init__(self, query="", max_depth=1, num_new_tags=5):
        self.query = query
        self.max_depth = max_depth
        self.num_new_tags = num_new_tags
        self.current_year = datetime.now().year
        self.bing_subscription_key = os.getenv('BING_SUBSCRIPTION_KEY', '')
        self.openai_api_key = os.getenv('OPENAI_API_KEY', '')
        self.endpoint = ""
        self.mkt = ''
        self.user_agent = ''
        self.robots_parsers = {}
        self.visited_urls = set()
        self.all_results = []
        self.full_query = f"thesis topic {self.current_year} {self.query}"

    def can_fetch_url(self, url):
        parsed_url = urlparse(url)
        robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
        if robots_url not in self.robots_parsers:
            rp = RobotFileParser()
            rp.set_url(robots_url)
            try:
                rp.read()
                self.robots_parsers[robots_url] = rp
            except Exception as e:
                print(f"Could not read robots.txt at {robots_url}: {e}")
                self.robots_parsers[robots_url] = None
                return False
        else:
            rp = self.robots_parsers[robots_url]
            if rp is None:
                return False
        return rp.can_fetch(self.user_agent, url)

    def process_search_results(self, results):
        structured_results = []
        if 'webPages' in results and 'value' in results['webPages']:
            for page in results['webPages']['value']:
                structured_object = {
                    'name': page.get('name'),
                    'url': page.get('url'),
                    'snippet': page.get('snippet'),
                    'displayUrl': page.get('displayUrl'),
                    'dateLastCrawled': page.get('dateLastCrawled'),
                }
                structured_results.append(structured_object)
        else:
            print("No web pages found in the search results.")
        return structured_results

    def fetch_bing_results(self, query):
        params = {'q': query, 'mkt': self.mkt}
        headers = {'Ocp-Apim-Subscription-Key': self.bing_subscription_key}
        try:
            response = requests.get(self.endpoint, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            print(f"An error occurred while fetching search results: {ex}")
            return None

    def extract_text_from_url(self, url):
        headers = {'User-Agent': self.user_agent}
        page_response = requests.get(url, headers=headers, timeout=10)
        page_response.raise_for_status()

        content_type = page_response.headers.get('Content-Type', '').lower()

        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            try:
                from io import BytesIO
                from PyPDF2 import PdfReader

                pdf_file = BytesIO(page_response.content)
                reader = PdfReader(pdf_file)
                text = ''
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + ' '
                text = ' '.join(text.split())
                print(f"Extracted text from PDF: {text[:100]}...")
                return text
            except Exception as e:
                # Handle exceptions, possibly logging them
                raise Exception(f"Failed to extract text from PDF: {e}")
        else:
            # Process HTML content
            page_content = page_response.text

            soup = BeautifulSoup(page_content, 'html.parser')
            for script_or_style in soup(['script', 'style']):
                script_or_style.decompose()

            text = soup.get_text(separator=' ', strip=True)
            text = ' '.join(text.split())
            return text

    def get_topics_from_text(self, text):
        import openai
        openai.api_key = self.openai_api_key

        messages = [
            {
                "role": "system",
                "content": "You are an assistant that extracts key research topics from text."
            },
            {
                "role": "user",
                "content": text[:5000]
            }
        ]

        client = OpenAI(api_key=self.openai_api_key)
        response = client.chat.completions.create(
            model="",
            messages=messages,
            max_tokens=self.num_new_tags * 20,
            temperature=0.5,
            n=1,
            stop=None
        )

        tags_text = response.choices[0].message.content
        return tags_text

    def recursive_search(self, query, depth):
        if depth > self.max_depth:
            return

        print(f"\nDepth {depth}: Searching for '{query}'")
        results = self.fetch_bing_results(query)
        if results is None:
            return

        search_results_list = self.process_search_results(results)
        current_results = []

        for result in search_results_list:
            url = result['url']
            if url in self.visited_urls:
                continue
            self.visited_urls.add(url)
            print(f"Processing URL: {url}")
            if self.can_fetch_url(url):
                try:
                    text = self.extract_text_from_url(url)
                    result['page_text'] = text
                    print(f"Successfully extracted text from {url}")

                    tags_text = self.get_topics_from_text(text)
                    result['extracted_topics'] = tags_text
                    # print(f"Extracted topics from {url}: {tags_text}")

                except Exception as e:
                    print(f"Error fetching {url}: {e}")
                    result['page_text'] = None
                    result['extracted_topics'] = None
            else:
                print(f"Not allowed to fetch {url} per robots.txt")
                result['page_text'] = None
                result['extracted_topics'] = None

            current_results.append(result)

        self.all_results.extend(current_results)

        if 'relatedSearches' in results and 'value' in results['relatedSearches']:
            for related in results['relatedSearches']['value']:
                related_query = related.get('text') or related.get('displayText')
                if related_query:
                    self.recursive_search(related_query, depth + 1)

    def generate_top_topics(self):

        all_extracted_topics = [result['extracted_topics'] for result in self.all_results if result['extracted_topics']]
        combined_topics_text = '\n'.join(all_extracted_topics)
        s = ""
        for i in range(1,self.num_new_tags+1):
            s += f"{i}. Topic {i}\n"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an assistant that aggregates and prioritizes research topics from multiple sources to "
                    "identify the top"+ str(self.num_new_tags)+" most relevant ones. You should provide a clear, concise list that strictly "
                    "follows the format provided below."
                )
            },
            {
                "role": "user",
                "content": f"""Given the following extracted topics from various sources, please provide a list of the top 10 most relevant research arxiv thesis search keywords for {self.current_year}. 
Be Short and concise.
Each topic should be listed in a numbered format from 1 to {self.num_new_tags}, with each number on a new line, followed by a period. 

Format your response as follows:
{s}

Here are the extracted topics for your reference:
{combined_topics_text}
"""
            }
        ]

        client = OpenAI(api_key=self.openai_api_key)
        response = client.chat.completions.create(
            model="",
            messages=messages,
            max_tokens=500,  # Adjust as needed
            temperature=0.5,
            n=1,
            stop=None
        )
        top_10_topics = response.choices[0].message.content.strip()
        return top_10_topics

    def run(self):
        self.recursive_search(self.full_query, depth=1)
        top_topics = self.generate_top_topics()
        # process top_topics to return a list of topics
        # there is a number followed by a period, followed by the topic
        top_topics = top_topics.split("\n")
        top_topics = [topic.split(".")[1].strip() for topic in top_topics if topic]
        return top_topics

# Example usage:
if __name__ == "__main__":
    generator = ThesisTopicGenerator(query="Deep reinforcement learning (RL) for robotic navigation and control", max_depth=1, num_new_tags=5)

    top_topics = generator.run()
    print(top_topics)