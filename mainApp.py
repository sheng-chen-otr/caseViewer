import streamlit as st
import os
import re
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import math

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="caseViewer-v0.1")

st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
</style>
""", unsafe_allow_html=True)

# --- PARSING LOGIC ---

def parse_filename(filename, folder_type):
    """
    Extracts metadata based on user rules.
    Returns: dict(view=str, sort_key=int/str, original=str)
    """
    name_no_ext = os.path.splitext(filename)[0]
    parts = name_no_ext.split('_')
    
    metadata = {
        'view': 'Unknown',
        'sort_key': 0,
        'filename': filename
    }

    # RULE 1: Slices (contains 'slices' in folder name)
    # "4th element is view", "6 digit number for sorting"
    if "slices" in folder_type.lower():
        if len(parts) >= 4:
            # Python lists are 0-indexed, so 4th element is index 3
            metadata['view'] = parts[3]
        
        # Regex to find the 6-digit number anywhere in the string
        match = re.search(r'(\d{6})', name_no_ext)
        if match:
            metadata['sort_key'] = int(match.group(1))
        else:
            # Fallback: try to find any number or use the name
            metadata['sort_key'] = name_no_ext

    # RULE 2: Surface (contains 'Surface' in folder name)
    # "Last string denotes view angle"
    elif "surface" in folder_type.lower():
        metadata['view'] = parts[-1]
        metadata['sort_key'] = 0 # Usually single image per view
        
    else:
        # Fallback for other folders
        metadata['view'] = "Default"
        metadata['sort_key'] = name_no_ext

    return metadata

def get_case_files(root_dir, case_id, variable_folder):
    """
    Returns a structured dictionary of files for a specific case/variable.
    Structure: { 'front': [file1, file2], 'top': [file1] }
    """
    path = os.path.join(root_dir, case_id, "postProcessing", "images", variable_folder)
    if not os.path.exists(path):
        return {}

    files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg'))]
    
    # Group files by View Angle
    grouped_files = {}
    
    for f in files:
        meta = parse_filename(f, variable_folder)
        view = meta['view']
        
        if view not in grouped_files:
            grouped_files[view] = []
        
        grouped_files[view].append(meta)
    
    # Sort the files within each view (crucial for slices)
    for view in grouped_files:
        grouped_files[view].sort(key=lambda x: x['sort_key'])
        
    return grouped_files

# --- HELPER FUNCTIONS ---

def get_subfolders(root_dir):
    if not os.path.exists(root_dir): return []
    return sorted([d for d in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, d)) and d.isdigit() and len(d)==3])

def get_image_folders(root_dir, case_id):
    path = os.path.join(root_dir, case_id, "postProcessing", "images")
    if not os.path.exists(path): return []
    return sorted([d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))])

@st.cache_data
def load_image(filepath, max_width=1200):
    try:
        img = Image.open(filepath)
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_height = int((float(img.height) * float(ratio)))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        return img
    except:
        return None

# --- PLOTTING ---

def create_plot(images_dict, view_mode, sync=True):
    titles = list(images_dict.keys())
    n_plots = len(titles)
    
    if n_plots == 0: return None

    # Determine Layout
    if view_mode == "Blink Comparator":
        fig = make_subplots(rows=1, cols=1)
        # Add traces
        for i, (case, img) in enumerate(images_dict.items()):
            visible = True if i == 0 else False
            fig.add_trace(go.Image(z=img, name=case, visible=visible))
        
        # Add Buttons
        buttons = []
        for i, case in enumerate(titles):
            # Create visibility list [False, False, True, False]
            vis_list = [False] * n_plots
            vis_list[i] = True
            buttons.append(dict(label=f"Show {case}", method="update", 
                              args=[{"visible": vis_list}, {"title": f"View: {case}"}]))
            
        fig.update_layout(updatemenus=[dict(type="buttons", direction="right", x=0.5, y=1.15, buttons=buttons)])
        
    else:
        # Side by Side or Grid
        cols = 2 if n_plots < 4 else 3
        rows = math.ceil(n_plots / cols)
        fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles, horizontal_spacing=0.02)
        
        idx = 0
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                if idx < n_plots:
                    case = titles[idx]
                    fig.add_trace(go.Image(z=images_dict[case]), row=r, col=c)
                    idx += 1
        
        if sync:
            fig.update_xaxes(matches='x')
            fig.update_yaxes(matches='y')

    # Common Cleanup
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(height=800, margin=dict(l=10, r=10, t=50, b=10))
    
    return fig

# --- MAIN APP ---

def main():
    st.title("🚀 CFD Comparative Viewer v3")

    with st.sidebar:
        st.header("1. Setup")
        root = st.text_input("Root Path", value=".")
        cases = get_subfolders(root)
        
        if not cases:
            st.warning("No cases found.")
            st.stop()
            
        # Select Cases
        mode = st.radio("Mode", ["Side-by-Side", "Grid View", "Blink Comparator"])
        
        if mode == "Grid View":
            sel_cases = st.multiselect("Select Cases", cases, default=cases[:4] if len(cases)>=4 else cases)
        else:
            c1 = st.selectbox("Case A", cases, index=0)
            c2 = st.selectbox("Case B", cases, index=1 if len(cases)>1 else 0)
            sel_cases = [c1, c2]

        if not sel_cases: st.stop()

        # Select Variable (Folder)
        # Scan Case A to populate options
        avail_vars = get_image_folders(root, sel_cases[0])
        if not avail_vars:
            st.warning(f"No image folders in {sel_cases[0]}")
            st.stop()
            
        variable = st.selectbox("Variable", avail_vars)

        # --- DYNAMIC METADATA PARSING ---
        st.header("2. View Controller")
        
        # Parse Case A to determine available Views (Front, Top, etc)
        # We assume Case A is the "Master" structure.
        case_a_data = get_case_files(root, sel_cases[0], variable)
        available_views = sorted(list(case_a_data.keys()))
        
        if not available_views:
            st.error("Could not parse views from filenames.")
            st.stop()
            
        selected_view = st.selectbox("Camera View", available_views)
        
        # Check if we have multiple slices (slider needed)
        # We check how many files are associated with this view in Case A
        files_in_view = case_a_data[selected_view]
        num_slices = len(files_in_view)
        
        slice_index = 0
        if num_slices > 1:
            st.info(f"Detected {num_slices} slices/frames.")
            slice_index = st.slider("Slice Position / Sequence", 0, num_slices-1, 0)
            
            # Display current file sorting key for context
            current_key = files_in_view[slice_index]['sort_key']
            st.caption(f"Current Sort Key: {current_key}")

    # --- LOAD DATA FOR ALL CASES ---
    images_to_plot = {}
    
    for case in sel_cases:
        # Get files for this case
        c_data = get_case_files(root, case, variable)
        
        # Check if this case has the selected view
        if selected_view in c_data:
            c_files = c_data[selected_view]
            
            # Logic: If slice_index exists, try to get that index. 
            # If this case has fewer slices, clamp to max.
            idx = min(slice_index, len(c_files)-1)
            
            file_meta = c_files[idx]
            full_path = os.path.join(root, case, "postProcessing", "images", variable, file_meta['filename'])
            
            images_to_plot[case] = load_image(full_path)
        else:
            st.warning(f"Case {case} missing view '{selected_view}'")
            images_to_plot[case] = None

    # --- RENDER ---
    fig = create_plot(images_to_plot, mode)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
