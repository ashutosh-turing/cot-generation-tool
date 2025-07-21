import re
import json
from datetime import datetime

class CodeToJsonConverter:
    def __init__(self):
        self.section_pattern = re.compile(r'\*\*\[SECTION_(\d+)\]\*\*')
        self.atomic_pattern = re.compile(r'\*\*\[atomic_(\d+)_(\d+)\]\*\*')

    def parse_code_file(self, file_content):
        """Parse the code file content and extract metadata and sections."""
        # Extract metadata
        metadata = self._extract_metadata(file_content)

        # Extract sections and their content
        sections = self._extract_sections(file_content)

        # Create the final JSON structure
        result = {
            "deliverable_id": self._generate_id(),
            "language": {
                "overall": "en_US"  # Default language
            },
            "notes": {
                "notebook_metadata": metadata,
                "annotator_ids": ["cDfeA"],  # Example annotator ID
                "task_category_list": [
                    {
                        "category": metadata.get("Category", ""),
                        "subcategory": metadata.get("Topic", "")
                    }
                ]
            },
            "messages": self._create_messages(file_content, sections)
        }

        return result

    def _extract_metadata(self, content):
        """Extract metadata from the file content."""
        metadata = {}
        metadata_section = re.search(r'# Metadata(.*?)#', content, re.DOTALL)

        if metadata_section:
            metadata_text = metadata_section.group(1)
            for line in metadata_text.split('\n'):
                if ':**' in line:
                    key, value = line.split(':**')
                    metadata[key.strip()] = value.strip()

        return metadata

    def _extract_sections(self, content):
        """Extract all sections and their atomic components."""
        sections = {}
        current_section = None
        current_atomic = None
        lines = content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]
            section_match = self.section_pattern.search(line)
            atomic_match = self.atomic_pattern.search(line)

            if section_match:
                current_section = section_match.group(1)
                sections[current_section] = {
                    "summary": "",
                    "atomics": {}
                }
                i += 1
                continue

            if atomic_match:
                if not current_section:
                    print(f"Warning: Found atomic marker before section marker at line: {line}")
                    i += 1
                    continue

                current_atomic = f"{atomic_match.group(1)}_{atomic_match.group(2)}"
                # Initialize the atomic content
                sections[current_section]["atomics"][current_atomic] = ""

                # Collect all content until the next atomic or section marker
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if self.section_pattern.search(next_line) or self.atomic_pattern.search(next_line):
                        break
                    sections[current_section]["atomics"][current_atomic] += next_line + "\n"
                    i += 1
                continue

            if current_section and line.strip():
                if not any(pattern.search(line) for pattern in [self.section_pattern, self.atomic_pattern]):
                    sections[current_section]["summary"] += line + "\n"

            i += 1

        return sections

    def _create_messages(self, content, sections):
        """Create the messages array for the JSON structure."""
        messages = [
            {
                "role": "user",
                "contents": [
                    {
                        "text": self._extract_prompt(content)
                    }
                ]
            },
            {
                "role": "assistant",
                "contents": [
                    {
                        "text": self._extract_response(content)
                    }
                ],
                "reasoning": {
                    "process": self._create_reasoning_process(sections)
                }
            }
        ]
        return messages

    def _extract_prompt(self, content):
        """Extract the original prompt from the content."""
        prompt_section = re.search(r'\*\*\[PROMPT\]\*\*(.*?)\*\*\[', content, re.DOTALL)
        return prompt_section.group(1).strip() if prompt_section else ""

    def _extract_response(self, content):
        """Extract the response section from the content."""
        response_section = re.search(r'\*\*\[RESPONSE\]\*\*(.*?)$', content, re.DOTALL)
        return response_section.group(1).strip() if response_section else ""

    def _create_reasoning_process(self, sections):
        """Create the reasoning process array from sections."""
        process = []
        # Sort sections by their numeric ID to maintain order
        for section_id in sorted(sections.keys(), key=int):
            section_data = sections[section_id]
            section_entry = {
                "summary": section_data["summary"].strip(),
                "thoughts": []
            }

            # Sort atomics by their IDs to maintain order
            for atomic_id in sorted(section_data["atomics"].keys()):
                atomic_content = section_data["atomics"][atomic_id]
                if atomic_content.strip():  # Only add non-empty thoughts
                    section_entry["thoughts"].append({
                        "text": atomic_content.strip()
                    })

            if section_entry["thoughts"]:  # Only add sections with thoughts
                process.append(section_entry)

        return process

    def _generate_id(self):
        """Generate a unique identifier."""
        return f"code-{datetime.now().strftime('%Y%m%d%H%M%S')}"

def convert_file_to_json(input_file_path, output_file_path):
    """Convert a code file to JSON format and save it."""
    try:
        converter = CodeToJsonConverter()

        # Read input file
        with open(input_file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Convert to JSON
        result = converter.parse_code_file(content)

        # Save JSON output
        with open(output_file_path, 'w', encoding='utf-8') as file:
            json.dump(result, file, indent=2, ensure_ascii=False)

        return result
    except FileNotFoundError:
        print(f"Error: Input file '{input_file_path}' not found.")
        return None
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return None
