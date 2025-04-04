"""
Converts a PDF file into structured Markdown format using PyMuPDF (fitz).

This script attempts uses heuristics based on font size, vertical spacing,
and text content to identify headings (H1-H3), paragraphs, and basic lists.
"""

# Standard library imports
import os
import re
import statistics
from collections import Counter

# Third-party imports
import fitz  # PyMuPDF

# --- Constants ---
# <<< CHANGE THESE TO YOUR FILE PATHS >>>
PDF_FILE = 'input.pdf'
MD_FILE = 'output.md'


def determine_font_styles(page):
    """Analyzes font sizes and flags on a page to guess body text size and heading levels."""
    styles = Counter()
    try:
        text_blocks = page.get_text(
            "dict",
            flags=fitz.TEXT_INHIBIT_SPACES | fitz.TEXT_PRESERVE_LIGATURES
        )["blocks"]
    except (fitz.Error, ValueError, KeyError) as e:
        print(f"Warning: Error getting text blocks from page {page.number + 1}: {e}")
        return None, {} # Cannot process page

    if not text_blocks:
        return None, {}  # No text blocks found

    all_sizes = []
    for block in text_blocks:
        if block['type'] == 0:  # Text block
            for line in block['lines']:
                for span in line['spans']:
                    size = round(span['size'])
                    all_sizes.append(size)
                    is_bold = (span['flags'] & 2**4) > 0
                    styles[(size, 'bold' if is_bold else 'normal')] += len(span['text'].strip())

    if not all_sizes:
        return None, {}  # No text found in blocks

    # --- Determine Body Size ---
    size_counts = Counter()
    for block in text_blocks:
        if block['type'] == 0:
            for line in block['lines']:
                for span in line['spans']:
                    size = round(span['size'])
                    size_counts[size] += len(span['text'].strip()) # Weight by text length

    if not size_counts:
        return None, {}

    # Find the size with the most characters (most likely body text)
    body_size = size_counts.most_common(1)[0][0] if size_counts else None
    if body_size is None:
        # Fallback if weighting fails (e.g., only headings present)
        body_size = statistics.mode(all_sizes) if all_sizes else 10  # Default guess

    # --- Determine Heading Sizes ---
    # Consider sizes significantly larger than body size
    heading_candidates = sorted(
        [s for s in list(set(all_sizes)) if s > body_size + 1], # +1 tolerance
        reverse=True
    )

    # Assign levels H1, H2, H3 based on distinct large sizes
    heading_levels = {}
    level = 1
    for size in heading_candidates:
        if level <= 3:  # Limit to H1, H2, H3 for simplicity
            heading_levels[size] = level
            level += 1
        else:
            break  # Stop assigning levels

    return body_size, heading_levels


def is_list_item(text):
    """Checks if a text line looks like a list item."""
    # Matches lines starting with *, -, +, bullet, number., letter. etc. + space/tab
    return re.match(r"^\s*([\*\-\+•]|\d+\.|[a-zA-Z]\.)\s+", text)


def convert_pdf_to_markdown(pdf_path, md_path):
    """Converts a PDF file to a structured Markdown file."""

    if not os.path.exists(pdf_path):
        print(f"Error: PDF file not found at {pdf_path}")
        return

    try:
        doc = fitz.open(pdf_path)
    except (IOError, RuntimeError, fitz.Error) as e: # Catch file, runtime, and fitz errors
        print(f"Error opening PDF file '{pdf_path}': {e}")
        return

    markdown_output = []
    last_block_bottom = 0

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        body_size, heading_levels = determine_font_styles(page)

        if body_size is None:  # Skip pages that couldn't be processed
            print(f"Info: Skipping page {page_num + 1} (no text or error processing).")
            continue

        # Extract blocks sorted by vertical, then horizontal position
        try:
            blocks = page.get_text(
                "dict",
                sort=True,
                flags=fitz.TEXT_INHIBIT_SPACES | fitz.TEXT_PRESERVE_LIGATURES
            )["blocks"]
        except (fitz.Error, ValueError, KeyError) as e:
            print(f"Warning: Error getting sorted text blocks from page {page_num + 1}: {e}")
            continue # Skip page if blocks cannot be retrieved

        markdown_output.append(f"\n<!-- Page {page_num + 1} -->\n")

        current_paragraph = ""

        for i, block in enumerate(blocks):
            if block.get('type') != 0:  # Skip non-text blocks (use .get for safety)
                continue

            block_text_lines = []
            block_avg_size = 0
            span_count = 0
            total_size = 0

            # Collect all text and calculate average size for the block
            for line in block.get('lines', []): # Use .get for safety
                line_text_parts = []
                for span in line.get('spans', []): # Use .get for safety
                    text = span.get('text', '')
                    size = round(span.get('size', body_size)) # Default to body size if missing
                    flags = span.get('flags', 0)

                    line_text_parts.append({
                        "text": text,
                        "size": size,
                        "bold": (flags & 2**4) > 0 # Bit 4 indicates bold
                    })
                    total_size += size * len(text) # Weighted size calculation
                    span_count += len(text)

                # Basic reassembly of lines
                block_text_lines.append(line_text_parts)

            if span_count > 0:
                block_avg_size = round(total_size / span_count)
            else:
                # Use body size or a default if block is effectively empty or lacks size info
                block_avg_size = body_size

            # --- Paragraph Spacing ---
            block_top = block.get('bbox', [0, 0, 0, 0])[1]
            block_bottom = block.get('bbox', [0, 0, 0, 0])[3]

            # Add paragraph break if significant vertical space exists
            # Heuristic: gap > 70% of body font height
            if page_num > 0 or i > 0: # Only add space after the very first block
                vertical_gap = block_top - last_block_bottom
                # Add break if gap is significant AND there was text in the previous block
                if vertical_gap > (body_size * 0.7) and markdown_output[-1] != "":
                    if current_paragraph: # Flush previous paragraph before adding space
                        markdown_output.append(current_paragraph.strip() + "\n")
                        current_paragraph = ""
                    markdown_output.append("") # Add a blank line for paragraph break

            # --- Heading Detection ---
            is_heading = False
            if block_avg_size in heading_levels:
                level = heading_levels[block_avg_size]
                # Aggregate text from spans for the heading
                heading_text = "".join(
                    span['text'] for line in block_text_lines for span in line
                ).strip()

                if heading_text: # Don't make empty headings
                    if current_paragraph: # Flush previous paragraph before heading
                        markdown_output.append(current_paragraph.strip() + "\n")
                        current_paragraph = ""
                    markdown_output.append("#" * level + " " + heading_text + "\n")
                    is_heading = True

            # --- List Detection & Paragraph Assembly ---
            if not is_heading:
                for line_parts in block_text_lines:
                    # Reconstruct line text for list checking and processing
                    line_text_raw = "".join(span['text'] for span in line_parts)
                    processed_line = ""
                    for span in line_parts:
                        text = span['text']
                        # Wrap bold text
                        if span['bold']:
                             # Avoid double-wrapping if already bold
                            if not processed_line.endswith("**") and not text.startswith("**"):
                                processed_line += f"**{text}**"
                            else:
                                processed_line += text # Already handled or adjacent
                        else:
                            processed_line += text

                    # Handle potential list items (check raw line text)
                    if is_list_item(line_text_raw):
                        if current_paragraph: # Flush previous paragraph before list
                            markdown_output.append(current_paragraph.strip() + "\n")
                            current_paragraph = ""
                        # Basic formatting: ensure marker kept, add line break
                        markdown_output.append(processed_line.strip() + "\n")
                    elif line_text_raw.strip(): # Regular text line
                        # Append to current paragraph, manage spacing
                        if current_paragraph and not current_paragraph.endswith("\n"):
                            current_paragraph += " " # Space between lines in same paragraph
                        current_paragraph += processed_line.strip() # Add the line content
                        # Note: Joining lines like this might merge lines that should be separate.
                        # More complex layout analysis would be needed for perfect line breaks.

            # Update position tracking using the current block's bottom
            last_block_bottom = block_bottom

        # Append any remaining text at the end of the page
        if current_paragraph:
            markdown_output.append(current_paragraph.strip() + "\n")
            current_paragraph = "" # Reset for next page


    # --- Final Output ---
    final_markdown = "\n".join(markdown_output)
    # Post-processing: Clean up excessive blank lines (3 or more become 2)
    final_markdown = re.sub(r'\n{3,}', '\n\n', final_markdown).strip()

    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(final_markdown)
        print(f"Successfully converted '{pdf_path}' to '{md_path}'")
    except IOError as e: # More specific exception for file writing
        print(f"Error writing Markdown file '{md_path}': {e}")

    finally:
        # Ensure document is closed even if errors occur during processing
        if 'doc' in locals() and doc:
            doc.close()


# --- How to use ---
# 1. Install PyMuPDF: pip install PyMuPDF
# 2. Set PDF_FILE and MD_FILE constants above.
# 3. Optional: Install ReportLab (pip install reportlab) to create dummy PDF.

# Example usage (using constants defined above)
# Optional: Create a dummy PDF for testing if needed
# Needs ReportLab: pip install reportlab
# try:
#     from reportlab.pdfgen import canvas
#     from reportlab.lib.pagesizes import letter
#     from reportlab.lib.styles import getSampleStyleSheet
#     from reportlab.platypus import Paragraph, Spacer

#     def create_dummy_pdf(filename="input.pdf"):
#         c = canvas.Canvas(filename, pagesize=letter)
#         styles = getSampleStyleSheet()
#         width, height = letter
#         story = []

#         # Title (H1)
#         story.append(Paragraph("My Document Title", styles['h1']))
#         story.append(Spacer(1, 0.2*72)) # 0.2 inch space

#         # Section 1 (H2)
#         story.append(Paragraph("Section 1: Introduction", styles['h2']))
#         story.append(Spacer(1, 0.1*72))

#         # Paragraph 1
#         text = ("This is the first paragraph. It contains some regular text "
#                 "explaining the purpose of this section. We can also add some "
#                 "<b>bold text</b> here.")
#         story.append(Paragraph(text, styles['Normal']))
#         story.append(Spacer(1, 0.1*72))

#         # Paragraph 2
#         text = ("This is the second paragraph, separated by some space. "
#                 "It discusses further points.")
#         story.append(Paragraph(text, styles['Normal']))
#         story.append(Spacer(1, 0.2*72))

#         # Section 2 (H2)
#         story.append(Paragraph("Section 2: Details", styles['h2']))
#         story.append(Spacer(1, 0.1*72))

#         # List
#         list_items = [
#             "* First item",
#             "* Second item with <b>bold</b> part.",
#             "* Third item."
#         ]
#         for item in list_items:
#             # Use a slightly indented style or add leading spaces manually if needed
#             # ReportLab paragraphs handle basic list markers well.
#             p = Paragraph(item, styles['Normal'])
#             # Add leftIndent to style for visual list indentation in PDF
#             # p.style.leftIndent = 18 # points
#             story.append(p)
#             story.append(Spacer(1, 0.05*72)) # Small space between list items

#         # Build the PDF content
#         frame_width = width - 100 # Margins
#         frame_height = height - 100
#         frame_x = 50
#         frame_y = 50

#         # Draw story onto canvas within a frame (simpler than absolute positioning)
#         frame = fitz.Frame(frame_x, frame_y, frame_width, frame_height,
#                            leftPadding=0, bottomPadding=0,
#                            rightPadding=0, topPadding=0)
#         # This is pseudo-code; ReportLab Platypus handles flowables differently.
#         # Using build method is standard.
#         from reportlab.platypus import SimpleDocTemplate
#         doc_template = SimpleDocTemplate(filename, pagesize=letter,
#                                          leftMargin=50, rightMargin=50,
#                                          topMargin=50, bottomMargin=50)
#         doc_template.build(story)

#         print(f"Created dummy PDF: {filename}")

#     if not os.path.exists(PDF_FILE):
#         try:
#             create_dummy_pdf(PDF_FILE)
#         except ImportError:
#             print("\nINFO: ReportLab not found (pip install reportlab). "
#                   "Cannot create dummy PDF.\nPlease provide your own input PDF.")
#         except Exception as e:
#             print(f"Error creating dummy PDF: {e}")

# except ImportError:
#      # Handle case where ReportLab check itself fails if it's not installed
#      if not os.path.exists(PDF_FILE):
#          print("\nINFO: ReportLab not found (pip install reportlab). "
#                "Cannot create dummy PDF.\nPlease provide your own input PDF.")
# except Exception as e:
#      print(f"An unexpected error occurred during setup: {e}")


# --- Run the Conversion ---
if __name__ == "__main__":
    if os.path.exists(PDF_FILE):
        convert_pdf_to_markdown(PDF_FILE, MD_FILE)
    elif PDF_FILE == 'input.pdf': # Only show info if default path wasn't changed
        print(f"\nINFO: Default '{PDF_FILE}' not found. "
              f"Please change the 'PDF_FILE' variable to your PDF's path.")