import os
import json
from openai import OpenAI

def analyze_reasoning_for_files(filepaths, api_key):
    """
    Analyzes logical reasoning for each JSON file in filepaths using the OpenAI API.
    
    Args:
        filepaths: List of paths to JSON files.
        api_key: Your OpenAI API key.

    Returns:
        A dictionary mapping each JSON file's basename to its analysis results.
    """
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    results = {}

    system_message = (
        "You are an AI language model that evaluates whether the current section logically follows "
        "the context and flow of the previous section. Each section consists of:\n"
        "- A summary: A high-level description of the section which you intend to achieve\n"
        "- Text: Details expanding on the summary, including logic, implementation insights, and reasoning.\n\n"
        "Your task is to:\n"
        "1. Check if the current section naturally follows the previous section's concepts.\n"
        "2. Ensure that no abrupt shifts in topic, missing logical connections, or contradictions exist.\n"
        "3. Verify that new elements in the current section are consistent with or expand upon what was established earlier.\n"
        "4. Identify any missing transitions that could cause a break in logical flow.\n"
        "5. If any inconsistencies or gaps exist, provide an explanation of the misalignment.\n"
        "6. Give an Overall Score Out of 5 for This Book in Integers."
    )

    for filepath in filepaths:
        try:
            with open(filepath, 'r') as file:
                data = json.load(file)
            
            # Extract the logical reasoning section
            thoughts_sections = data["messages"][1]["reasoning"]["process"]
            
            prompt = (
                f"Evaluate whether the following section logically follows the preceding section in terms of context and flow. "
                f"Identify any gaps, inconsistencies, or abrupt transitions.\n\n"
                f"Sections:\n{thoughts_sections}"
            )
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                stream=False
            )
            analysis = response.choices[0].message.content
        except Exception as e:
            analysis = f"Error processing {os.path.basename(filepath)}: {str(e)}"
        
        results[os.path.basename(filepath)] = analysis

    return results

# Example usage:
if __name__ == "__main__":
    api_key = "your_api_key_here"  # Replace with your actual OpenAI API key
    filepaths = [
        "/path/to/first_file.json",
        "/path/to/second_file.json"
    ]
    analysis_results = analyze_reasoning_for_files(filepaths, api_key)
    for filename, result in analysis_results.items():
        print(f"Analysis for {filename}:")
        print(result)
        print("-" * 40)