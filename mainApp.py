import streamlit as st
import os
import re
import math
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="CFD Pro Viewer v12 - Stable")

st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
    /* Load Button */
    div.stButton > button:first-child {
        background-color: #00ADB5;
        color: white;
        font-weight: bold;
        border: none;
        width: 100%;
        margin-top: 20px;
    }
    /* Download Button Styling */
    .stDownloadButton > button {
        width: 100%;
        border: 1px solid #444;
    }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS ---
OPENFOAM_BASE_DIR = "/home/openfoam/openFoam/run"

# --- STATE MANAGEMENT ---
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

def reset_state():
    st.session_state.data_loaded = False

# --- 1. PARSING LOGIC ---
def parse_metadata(filename):
    name_no_ext = os.path.splitext(filename)[0]
    parts = name_no_ext.split('_')
    metadata = {'view': 'Default', 'sort_key': 0, 'filename': filename}

    if len(parts) > 3: metadata['view'] = parts[3]
    else: metadata['view'] = parts[-1]

    match = re.search(r'(\d{6})', name_no_ext)
    if match: metadata['sort_key'] = int(match.group(1))
    else:
        nums = re.findall(r'\d+', name_no_ext)
        if nums: metadata['sort_key'] = int(nums[-1])
    return metadata

# --- 2. DATA LOADING (Server Cache) ---
@st.cache_resource(show_spinner=False)
def load_data_into_ram(root_dir, selected_cases, variable_folder):
    """
    Loads images into Server RAM.
    Downsamples strictly for DISPLAY, but keeps path for DOWNLOAD.
    """
    dataset = {}
    MAX_WIDTH = 1000  # Safe for display speed
    
    progress_bar = st.progress(0, text="Loading into Server Memory...")
    
    for i, case in enumerate(selected_cases):
        path = os.path.join(root_dir, case, "postProcessing", "images", variable_folder)
        if not os.path.exists(path): continue

        dataset[case] = {}
        files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        for f in files:
            meta = parse_metadata(f)
            view = meta['view']
            if view not in dataset[case]: dataset[case][view] = []
            
            try:
                full_path = os.path.join(path, f)
                img = Image.open(full_path)
                
                # Create Display Version (Small)
                if img.width > MAX_WIDTH:
                    ratio = MAX_WIDTH / float(img.width)
                    new_height = int((float(img.height) * float(ratio)))
                    img_display = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
                else:
                    img_display = img

                # We store: (SortKey, DisplayImage, OriginalPath)
                dataset[case][view].append((meta['sort_key'], img_display, full_path))
            except: pass

        for view in dataset[case]:
            dataset[case][view].sort(key=lambda x: x[0])
            
        progress_bar.progress((i + 1) / len(selected_cases), text=f"Loaded Case {case}")

    progress_bar.empty()
    return dataset

# --- 3. STATIC PLOTTING ENGINE ---
def render_static_plot(data_map, case_names, mode, sync=True):
    """
    Renders a SINGLE time step.
    data_map: { 'CaseName': PIL_Image_Object }
    """
    
    # --- BLINK COMPARATOR (Lightweight JS Toggle) ---
    if mode == "Blink Comparator":
        fig = make_subplots(rows=1, cols=1)
        
        # We only have 2 images here (Current time step for Case A and Case B)
        # This is very light on the browser.
        img_a = data_map.get(case_names[0])
        img_b = data_map.get(case_names[1])

        if img_a: fig.add_trace(go.Image(z=img_a, name=case_names[0], visible=True))
        if img_b: fig.add_trace(go.Image(z=img_b, name=case_names[1], visible=False)) # Hidden initially

        # JS Buttons to toggle visibility locally
        buttons = [
            dict(label=f"Show {case_names[0]}", method="update", 
                 args=[{"visible": [True, False]}, {"title": f"View: {case_names[0]}"}]),
            dict(label=f"Show {case_names[1]}", method="update", 
                 args=[{"visible": [False, True]}, {"title": f"View: {case_names[1]}"}])
        ]
        
        fig.update_layout(
            updatemenus=[dict(type="buttons", direction="right", x=0.5, y=1.15, buttons=buttons)],
            title_text=f"Active: {case_names[0]}"
        )

    # --- GRID / SIDE-BY-SIDE ---
    else:
        n_plots = len(case_names)
        cols = 2 if n_plots < 4 else 3
        rows = math.ceil(n_plots / cols)
        
        fig = make_subplots(rows=rows, cols=cols, subplot_titles=case_names, 
                            horizontal_spacing=0.01, vertical_spacing=0.05)
        
        idx = 0
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                if idx < n_plots:
                    case = case_names[idx]
                    img = data_map.get(case)
                    if img:
                        fig.add_trace(go.Image(z=img), row=r, col=c)
                    idx += 1
        
        if sync:
            fig.update_xaxes(matches='x')
            fig.update_yaxes(matches='y')

    # Common Polish
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(height=800, margin=dict(l=10, r=10, t=50, b=10))

    return fig

# --- 4. MAIN APP ---
def main():
    st.title("🚀 CFD Pro Viewer v12 (Stable)")

    # --- SIDEBAR: SETUP ---
    with st.sidebar:
        st.header("1. Job Selection")
        
        if os.path.exists(OPENFOAM_BASE_DIR):
            base_path = OPENFOAM_BASE_DIR
            available_jobs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
        else:
            base_path = "." 
            available_jobs = sorted([d for d in os.listdir(".") if os.path.isdir(d)])

        selected_job = st.selectbox("Select Job", available_jobs, index=None, placeholder="Choose job...", on_change=reset_state)
        if not selected_job: st.stop()

        cases_root = os.path.join(base_path, selected_job, "CASES")
        if not os.path.exists(cases_root): st.stop()
        
        all_cases = sorted([d for d in os.listdir(cases_root) if d.isdigit() and len(d)==3])
        if not all_cases: st.error("No cases."); st.stop()

        # Variable Selection
        master_structure_case = all_cases[0]
        img_path = os.path.join(cases_root, master_structure_case, "postProcessing", "images")
        avail_vars = []
        if os.path.exists(img_path):
            avail_vars = sorted([d for d in os.listdir(img_path) if os.path.isdir(os.path.join(img_path, d))])
        
        variable = st.selectbox("Variable", avail_vars, index=None, placeholder="Choose variable...", key="var_select", on_change=reset_state)

        # Mode Selection
        mode = st.radio("Display Mode", ["Side-by-Side", "Grid View", "Blink Comparator"], on_change=reset_state)
        
        selected_cases = []
        if mode == "Grid View":
            selected_cases = st.multiselect("Select Cases", all_cases, default=[], placeholder="Select cases...", on_change=reset_state)
        else:
            col1, col2 = st.columns(2)
            c1 = col1.selectbox("Case A", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            c2 = col2.selectbox("Case B", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            if c1 and c2: selected_cases = [c1, c2]

        st.divider()

        if not st.session_state.data_loaded:
            if not selected_cases or not variable: st.stop()
            if st.button("LOAD DATA 🚀"):
                st.session_state.data_loaded = True
                st.rerun()
            else: st.stop()

    # --- EXECUTION ---
    dataset = load_data_into_ram(cases_root, selected_cases, variable)

    # --- VIEW CONTROLS (Top of Main Area for better UX) ---
    with st.sidebar:
        st.header("2. View Controls")
        master_case = selected_cases[0]
        if master_case not in dataset: st.stop()

        available_views = sorted(list(dataset[master_case].keys()))
        view_selection = st.selectbox("Camera View", available_views)
        
        master_seq = dataset[master_case][view_selection]
        num_frames = len(master_seq)
        
        # --- THE SERVER-SIDE SLIDER ---
        st.write("---")
        frame_index = st.slider("Slice / Time Step", 0, num_frames - 1, 0)
        
        # Get Info for current frame
        current_sort_key = master_seq[frame_index][0]
        st.caption(f"Sort Key: {current_sort_key} | Frame: {frame_index}/{num_frames-1}")

    # --- PREPARE SINGLE FRAME DATA ---
    current_frame_map = {} # For Plotting (Resized)
    download_map = {}      # For Downloading (Original Path)

    for case in selected_cases:
        if case in dataset and view_selection in dataset[case]:
            seq = dataset[case][view_selection]
            # Safety clamp
            idx = min(frame_index, len(seq)-1)
            
            # Unpack: (SortKey, ImgDisplay, FullPath)
            _, img_disp, full_path = seq[idx]
            
            current_frame_map[case] = img_disp
            download_map[case] = full_path
        else:
            current_frame_map[case] = None

    # --- RENDER ---
    fig = render_static_plot(current_frame_map, selected_cases, mode)
    st.plotly_chart(fig, use_container_width=True)

    # --- DOWNLOAD BUTTONS (Linked to Slider) ---
    st.markdown("---")
    st.subheader("📥 Download Current View (Original 4K)")
    
    dl_cols = st.columns(len(selected_cases))
    
    for i, case in enumerate(selected_cases):
        with dl_cols[i]:
            path = download_map.get(case)
            if path and os.path.exists(path):
                file_name = os.path.basename(path)
                with open(path, "rb") as f:
                    st.download_button(
                        label=f"💾 {case}: {file_name}",
                        data=f,
                        file_name=file_name,
                        mime="image/png",
                        key=f"dl_{case}_{frame_index}"
                    )
            else:
                st.warning(f"File not found for {case}")

if __name__ == "__main__":
    main()
