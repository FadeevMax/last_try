import streamlit as st
import os
import json
import base64
import requests
from pathlib import Path
import traceback
from dataclasses import dataclass
from typing import List, Dict, Any
import io

# Set page config
st.set_page_config(
    page_title="GTI SOP Chatbot - Simple",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration
GITHUB_REPO = os.getenv('GITHUB_REPO', 'FadeevMax/last_try')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
GITHUB_BRANCH = 'image-storage'

@dataclass
class TextElement:
    text: str
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    font_size: int = 12

@dataclass
class ImageElement:
    filename: str
    url: str
    label: str
    width: int = None
    height: int = None

@dataclass
class BlockContent:
    elements: List[Any]  # Mix of TextElement and ImageElement
    
@dataclass
class DocumentBlock:
    tab_title: str
    block_title: str
    content: BlockContent
    full_text: str  # For search purposes

class SimpleDocumentProcessor:
    def __init__(self):
        self.image_counter = 1
    
    def upload_image_to_github(self, filename: str, content: bytes) -> str:
        """Upload image to GitHub and return URL"""
        if not GITHUB_TOKEN:
            return None
            
        content_base64 = base64.b64encode(content).decode('utf-8')
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/images/{filename}"
        
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Check if file exists
        response = requests.get(url, headers=headers)
        sha = response.json().get('sha') if response.status_code == 200 else None
        
        data = {
            "message": f"Upload {filename}",
            "content": content_base64,
            "branch": GITHUB_BRANCH
        }
        
        if sha:
            data["sha"] = sha
        
        response = requests.put(url, headers=headers, json=data)
        
        if response.status_code in [200, 201]:
            return response.json()['content']['download_url']
        return None
    
    def extract_text_formatting(self, run):
        """Extract text formatting from a run"""
        return TextElement(
            text=run.text,
            is_bold=run.bold if run.bold is not None else False,
            is_italic=run.italic if run.italic is not None else False,
            is_underline=run.underline if run.underline is not None else False,
            font_size=run.font.size.pt if run.font.size else 12
        )
    
    def process_docx(self, file_content: bytes) -> List[DocumentBlock]:
        """Process DOCX file into structured blocks"""
        try:
            from docx import Document
            from docx.oxml.ns import qn
            import re
            
            doc = Document(io.BytesIO(file_content))
            blocks = []
            current_tab = "General"
            current_block_title = ""
            current_elements = []
            
            def save_current_block():
                if current_elements and current_block_title:
                    # Build full text for search
                    full_text = f"{current_tab} - {current_block_title}\n"
                    for elem in current_elements:
                        if isinstance(elem, TextElement):
                            full_text += elem.text + " "
                        elif isinstance(elem, ImageElement):
                            full_text += f"[Image: {elem.label}] "
                    
                    blocks.append(DocumentBlock(
                        tab_title=current_tab,
                        block_title=current_block_title,
                        content=BlockContent(elements=current_elements.copy()),
                        full_text=full_text.strip()
                    ))
                    current_elements.clear()
            
            def is_heading_2(paragraph):
                """Check if paragraph is Heading 2 style"""
                return (paragraph.style.name == 'Heading 2' or 
                        (paragraph.runs and len(paragraph.runs) > 0 and 
                         paragraph.runs[0].font.size and 
                         paragraph.runs[0].font.size.pt >= 14 and
                         paragraph.runs[0].bold))
            
            def is_block_delimiter(paragraph):
                """Check if paragraph is a block delimiter (BOLD UPPERCASE ending with :)"""
                text = paragraph.text.strip()
                if not text.endswith(':'):
                    return False
                
                # Check if all runs are bold and text is uppercase
                if not paragraph.runs:
                    return False
                
                all_bold = all(run.bold for run in paragraph.runs if run.text.strip())
                is_uppercase = text.isupper()
                
                return all_bold and is_uppercase and len(text) > 3
            
            def extract_images_from_paragraph(paragraph):
                """Extract images from paragraph"""
                images = []
                for run in paragraph.runs:
                    if 'graphic' in run._element.xml:
                        for drawing in run._element.findall(".//w:drawing", namespaces=run._element.nsmap):
                            for blip in drawing.findall(".//a:blip", namespaces=run._element.nsmap):
                                rel_id = blip.get(qn('r:embed'))
                                if rel_id and rel_id in doc.part.related_parts:
                                    image_part = doc.part.related_parts[rel_id]
                                    
                                    # Generate filename
                                    image_extension = image_part.content_type.split('/')[-1]
                                    if image_extension == 'jpeg':
                                        image_extension = 'jpg'
                                    elif image_extension not in ['jpg', 'png', 'gif', 'bmp', 'webp']:
                                        image_extension = 'png'
                                    
                                    filename = f"image_{self.image_counter}.{image_extension}"
                                    
                                    # Upload to GitHub
                                    url = self.upload_image_to_github(filename, image_part.blob)
                                    
                                    # Try to find label in surrounding text
                                    label = self.find_image_label(paragraph.text, self.image_counter)
                                    
                                    images.append(ImageElement(
                                        filename=filename,
                                        url=url,
                                        label=label,
                                    ))
                                    
                                    self.image_counter += 1
                
                return images
            
            # Process all paragraphs
            for para in doc.paragraphs:
                text = para.text.strip()
                
                if not text:
                    continue
                
                # Check for new tab (Heading 2)
                if is_heading_2(para):
                    save_current_block()
                    current_tab = text
                    current_block_title = ""
                    continue
                
                # Check for block delimiter
                if is_block_delimiter(para):
                    save_current_block()
                    current_block_title = text
                    continue
                
                # Regular content
                if current_block_title:  # Only add content if we're in a block
                    # Extract images first
                    images = extract_images_from_paragraph(para)
                    for img in images:
                        current_elements.append(img)
                    
                    # Extract formatted text
                    if text:  # Only add text if there's actual text content
                        for run in para.runs:
                            if run.text.strip():
                                text_elem = self.extract_text_formatting(run)
                                current_elements.append(text_elem)
                        
                        # Add paragraph break
                        current_elements.append(TextElement(text="\n", is_bold=False))
            
            # Save final block
            save_current_block()
            
            return blocks
            
        except Exception as e:
            st.error(f"Error processing document: {e}")
            st.code(traceback.format_exc())
            return []
    
    def find_image_label(self, text: str, image_number: int) -> str:
        """Find image label from text"""
        import re
        
        # Look for "Image X:" pattern
        pattern = rf"Image\s+{image_number}\s*[:.]?\s*([^.]*)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"Image {image_number}: {match.group(1).strip()}"
        
        # Look for "Figure X:" pattern
        pattern = rf"Figure\s+{image_number}\s*[:.]?\s*([^.]*)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"Figure {image_number}: {match.group(1).strip()}"
        
        # Default label
        return f"Image {image_number}"

class SimpleChatbot:
    def __init__(self):
        self.openai_key = ""
        self.gemini_key = ""
    
    def setup_keys(self, openai_key: str, gemini_key: str):
        self.openai_key = openai_key
        self.gemini_key = gemini_key
    
    def search_blocks(self, blocks: List[DocumentBlock], query: str, top_k: int = 3) -> List[DocumentBlock]:
        """Simple keyword-based search"""
        query_words = set(query.lower().split())
        scored_blocks = []
        
        for block in blocks:
            text_words = set(block.full_text.lower().split())
            
            # Calculate overlap score
            overlap = len(query_words.intersection(text_words))
            if overlap > 0:
                score = overlap / len(query_words)
                scored_blocks.append((block, score))
        
        # Sort by score and return top results
        scored_blocks.sort(key=lambda x: x[1], reverse=True)
        return [block for block, score in scored_blocks[:top_k]]
    
    def generate_response(self, model: str, blocks: List[DocumentBlock], query: str) -> str:
        """Generate AI response"""
        if not blocks:
            return "I couldn't find any relevant information for your question."
        
        # Build context from blocks
        context_parts = [f"User Question: {query}\n\nRelevant Documentation:"]
        
        for i, block in enumerate(blocks):
            context_parts.append(f"\n--- {block.tab_title} > {block.block_title} ---")
            context_parts.append(block.full_text)
        
        context = '\n'.join(context_parts)
        context += "\n\nPlease provide a clear answer based only on the information above."
        
        if model == "Gemini 2.0 Flash" and self.gemini_key:
            return self._generate_gemini(context)
        elif "GPT" in model and self.openai_key:
            return self._generate_openai(context, model)
        else:
            return "⚠️ Please configure API keys in the sidebar to use AI models."
    
    def _generate_gemini(self, context: str) -> str:
        try:
            headers = {
                'Content-Type': 'application/json',
                'X-goog-api-key': self.gemini_key
            }
            
            data = {
                "contents": [{"parts": [{"text": context}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 1000
                }
            }
            
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    return result['candidates'][0]['content']['parts'][0]['text']
            
            return f"Error: {response.status_code} - {response.text}"
            
        except Exception as e:
            return f"Error calling Gemini: {str(e)}"
    
    def _generate_openai(self, context: str, model: str) -> str:
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=self.openai_key)
            
            model_map = {
                "GPT-4.1": "gpt-4.1",
                "GPT-4 Mini": "gpt-4o-mini"
            }
            
            response = client.chat.completions.create(
                model=model_map.get(model, "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a GTI SOP Assistant. Answer based ONLY on provided documentation."},
                    {"role": "user", "content": context}
                ],
                max_tokens=1000,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Error calling OpenAI: {str(e)}"

def render_block_content(block: DocumentBlock):
    """Render block content with preserved formatting"""
    st.markdown(f"### {block.tab_title} > {block.block_title}")
    
    current_text = ""
    
    for element in block.content.elements:
        if isinstance(element, TextElement):
            if element.text == "\n":
                # Paragraph break - render accumulated text and start new line
                if current_text.strip():
                    st.markdown(current_text)
                    current_text = ""
                st.write("")  # Add space
            else:
                # Accumulate formatted text
                text = element.text
                if element.is_bold:
                    text = f"**{text}**"
                if element.is_italic:
                    text = f"*{text}*"
                if element.is_underline:
                    text = f"<u>{text}</u>"
                
                current_text += text
        
        elif isinstance(element, ImageElement):
            # Render any accumulated text first
            if current_text.strip():
                st.markdown(current_text, unsafe_allow_html=True)
                current_text = ""
            
            # Render image
            if element.url:
                st.image(element.url, caption=element.label, use_container_width=True)
            else:
                st.error(f"Could not load image: {element.label}")
    
    # Render any remaining text
    if current_text.strip():
        st.markdown(current_text, unsafe_allow_html=True)

def get_docx_from_github(repo="FadeevMax/cmon", path="GTI_Data_Base_and_SOP.docx", branch="main"):
    """Download DOCX from GitHub"""
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"Failed to fetch DOCX: {response.status_code}")
    except Exception as e:
        st.error(f"Error fetching DOCX: {str(e)}")
    return None

# Initialize session state
if 'blocks' not in st.session_state:
    st.session_state.blocks = []
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'processor' not in st.session_state:
    st.session_state.processor = SimpleDocumentProcessor()
if 'chatbot' not in st.session_state:
    st.session_state.chatbot = SimpleChatbot()

# CSS
st.markdown("""
<style>
.main-header { 
    font-size: 2.5rem; 
    font-weight: bold; 
    background: linear-gradient(90deg, #1e3c72, #2a5298);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-align: center;
    margin-bottom: 2rem;
}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<h1 class="main-header">🚀 GTI SOP Chatbot - Simple</h1>', unsafe_allow_html=True)
st.markdown("*Simple chatbot that preserves document structure and formatting*")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Load API keys from environment
    openai_key_default = os.getenv('OPENAI_API_KEY', '')
    gemini_key_default = os.getenv('GEMINI_API_KEY', '')
    
    with st.expander("🔑 API Keys"):
        gemini_key = st.text_input("Gemini API Key", value=gemini_key_default, type="password")
        openai_key = st.text_input("OpenAI API Key", value=openai_key_default, type="password")
        
        if st.button("💾 Save Keys"):
            st.session_state.chatbot.setup_keys(openai_key, gemini_key)
            st.success("Keys saved!")
    
    # Model selection
    model = st.selectbox(
        "🤖 AI Model",
        ["GPT-4.1", "Gemini 2.0 Flash", "GPT-4 Mini"],
        help="Choose your preferred AI model"
    )
    
    st.divider()
    st.header("📊 Status")
    
    if st.session_state.blocks:
        st.success(f"✅ Document loaded ({len(st.session_state.blocks)} blocks)")
    else:
        st.warning("⏳ No document loaded")

# Main interface
col1, col2 = st.columns([6, 1])

with col1:
    st.markdown("### 💬 Chat with GTI SOP")

with col2:
    if st.button("☁️ Load SOP", help="Download and process latest SOP from GitHub"):
        with st.spinner("Loading document..."):
            file_content = get_docx_from_github()
            if file_content:
                blocks = st.session_state.processor.process_docx(file_content)
                if blocks:
                    st.session_state.blocks = blocks
                    st.success(f"✅ Loaded {len(blocks)} blocks!")
                else:
                    st.error("❌ Failed to process document")
            else:
                st.error("❌ Failed to download document")

# Upload alternative
uploaded_file = st.file_uploader("Or upload your own DOCX file", type=["docx"])
if uploaded_file:
    with st.spinner("Processing document..."):
        file_content = uploaded_file.read()
        blocks = st.session_state.processor.process_docx(file_content)
        if blocks:
            st.session_state.blocks = blocks
            st.success(f"✅ Processed {len(blocks)} blocks!")

# Chat interface
if st.session_state.blocks:
    # Setup API keys
    st.session_state.chatbot.setup_keys(openai_key, gemini_key)
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and "blocks" in message:
                # Render the AI response
                st.write(message["content"])
                # Render the associated blocks
                for block in message["blocks"]:
                    with st.expander(f"📄 {block.tab_title} > {block.block_title}"):
                        render_block_content(block)
            else:
                st.write(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about GTI procedures..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.write(prompt)
        
        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Searching and generating response..."):
                # Search for relevant blocks
                relevant_blocks = st.session_state.chatbot.search_blocks(
                    st.session_state.blocks, prompt, top_k=3
                )
                
                if relevant_blocks:
                    # Generate AI response
                    answer = st.session_state.chatbot.generate_response(
                        model, relevant_blocks, prompt
                    )
                    
                    st.write(answer)
                    
                    # Display relevant blocks with preserved formatting
                    for block in relevant_blocks:
                        with st.expander(f"📄 {block.tab_title} > {block.block_title}"):
                            render_block_content(block)
                    
                    # Save assistant message with blocks
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": answer,
                        "blocks": relevant_blocks
                    })
                else:
                    answer = "I couldn't find relevant information for your query. Please try rephrasing your question."
                    st.write(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})

    # Clear chat
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.rerun()

else:
    st.info("👆 Please load a document first by clicking 'Load SOP' or uploading a file.")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: #666; margin-top: 2rem;'>
    <p>🚀 GTI SOP Chatbot - Simple Version</p>
    <p>Preserves original document structure and formatting</p>
</div>
""", unsafe_allow_html=True)
