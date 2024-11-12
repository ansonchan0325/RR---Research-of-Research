import arxiv
import os
import csv
import zlib
import pandas as pd
import calendar


class ArxivResearchHelper:
    def __init__(self, download_dir="downloads", page_size=10, delay_seconds=3.0, num_retries=3):
        self.download_dir = download_dir
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        # Initialize the arxiv.Client with custom settings
        self.client = arxiv.Client(
            page_size=page_size,
            delay_seconds=delay_seconds,
            num_retries=num_retries
        )

    def search_papers(self, query, max_results=50, date_from=None, date_to=None):
        """
        Search for papers on arXiv with an optional date range.

        Parameters:
        - query (str): The search query.
        - max_results (int): Maximum number of results to return.
        - date_from (str): Start date in 'YYYYMM' format.
        - date_to (str): End date in 'YYYYMM' format.

        Returns:
        - List of dictionaries containing paper details.
        """
        # Build the date range query if date_from or date_to is specified
        if date_from or date_to:
            date_query = "submittedDate:["
            # Start date
            if date_from:
                date_from_str = f"{date_from}01"
                date_query += f"{date_from_str} TO "
            else:
                date_query += "* TO "
            # End date
            if date_to:
                year = int(date_to[:4])
                month = int(date_to[4:])
                last_day = calendar.monthrange(year, month)[1]
                date_to_str = f"{date_to}{last_day}"
                date_query += f"{date_to_str}]"
            else:
                date_query += "*]"
            # Combine the main query with the date range query
            query = f"({query}) AND {date_query}"

        # Create the search object
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate  # Sort by submission date
        )

        results = []
        try:
            # Fetch results and store in a list
            for result in self.client.results(search):
                paper = {
                    "hash_id": zlib.crc32(bytes(result.entry_id, 'utf-8')),
                    "title": result.title,
                    "authors": ", ".join([author.name for author in result.authors]),
                    "published": result.published,
                    "summary": result.summary,
                    "pdf_url": result.pdf_url,
                    "entry_id": result.entry_id,
                }
                results.append(paper)

                if len(results) >= max_results:
                    break  # Stop if we reach the max results limit
        except Exception as e:
            print(f"Error while fetching results: {e}")

        return results

    def download_pdf(self, entry_id):
        """Download the PDF of a paper given its entry_id."""
        try:
            paper = next(self.client.results(arxiv.Search(id_list=[entry_id])))
            pdf_url = paper.pdf_url
            title = paper.title.replace(" ", "_").replace("/", "_")  # Ensure valid filename
            pdf_filename = os.path.join(self.download_dir, f"{title}.pdf")

            if os.path.exists(pdf_filename):
                print(f"PDF already exists: {pdf_filename}")
                return pdf_filename

            # Download the PDF
            print(f"Downloading PDF: {pdf_url}")
            paper.download_pdf(dirpath=self.download_dir, filename=f"{title}.pdf")
            return pdf_filename
        except Exception as e:
            print(f"Error while downloading PDF: {e}")
            return None

    def save_papers_to_csv(self, papers, filename="papers.csv"):
        """Save the search results into a CSV file."""
        header = ["hash_id", "title", "authors", "published", "summary", "pdf_url", "entry_id"]

        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=header)

                # Write the header row
                writer.writeheader()

                # Write the data rows (each paper as a row)
                for paper in papers:
                    writer.writerow(paper)

            print(f"Saved {len(papers)} papers to {filename}")
        except Exception as e:
            print(f"Error while saving to CSV: {e}")




