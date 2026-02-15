import streamlit as st
import os
import re
import math
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="CFD Pro Viewer v7 - Fast Scroll")

st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS ---
OPENFOAM_BASE_DIR = "/home/openfoam/openFoam/run"

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

# --- 2. DATA LOADING ---
@st.cache_resource(show_spinner=False)
def load_data_into_ram(root_dir, selected_cases, variable_folder):
    dataset = {}
    # Downsample to 1000px to keep browser memory usage safe during animation
    MAX_WIDTH = 1000 
    
    progress_bar = st.progress(0, text="Loading & Pre-processing...")
    
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
                if img.width > MAX_WIDTH:
                    ratio = MAX_WIDTH / float(img.width)
                    new_height = int((float(img.height) * float(ratio)))
                    img = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
                dataset[case][view].append((meta['sort_key'], img))
            except: pass

        for view in dataset[case]:
            dataset[case][view].sort(key=lambda x: x[0])
            
        progress_bar.progress((i + 1) / len(selected_cases), text=f"Loaded Case {case}")

    progress_bar.empty()
    return dataset

# --- 3. ANIMATION ENGINE (THE FIX) ---
def render_animated_plot(data_sequences, case_names, mode, sync=True):
    """
    data_sequences: dict { 'CaseName': [PIL_Images...] }
    All sequences MUST be the same length for animation to work correctly.
    """
    
    # 1. Determine Grid Layout
    n_plots = len(case_names)
    cols = 2 if n_plots < 4 else 3
    rows = math.ceil(n_plots / cols)
    
    # 2. Setup Base Figure (First Frame)
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=case_names, 
                        horizontal_spacing=0.01, vertical_spacing=0.05)
    
    # Add initial traces (Time Step 0)
    idx = 0
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            if idx < n_plots:
                case = case_names[idx]
                # Get first image
                first_img = data_sequences[case][0] if data_sequences[case] else None
                fig.add_trace(go.Image(z=first_img), row=r, col=c)
                idx += 1

    # 3. Construct Frames (The Magic Part)
    # We assume all cases have roughly the same number of steps. 
    # We take the length of the first case as the master timeline.
    master_len = len(data_sequences[case_names[0]])
    frames = []

    for k in range(master_len):
        frame_data = []
        # For this specific time step k, gather images for ALL cases
        for case in case_names:
            seq = data_sequences[case]
            # Safety: if this case is shorter, use its last frame
            img_idx = min(k, len(seq)-1)
            frame_data.append(go.Image(z=seq[img_idx]))
        
        # Create the frame object
        frames.append(go.Frame(data=frame_data, name=str(k)))

    fig.frames = frames

    # 4. Add Client-Side Slider
    steps = []
    for k in range(master_len):
        steps.append(dict(
            method="animate",
            args=[[str(k)], dict(mode="immediate", frame=dict(duration=0, redraw=True), transition=dict(duration=0))],
            label=str(k)
        ))

    sliders = [dict(
        active=0,
        currentvalue={"prefix": "Slice / Time: "},
        pad={"t": 50},
        steps=steps
    )]

    fig.update_layout(sliders=sliders)

    # 5. Sync & Polish
    if sync:
        fig.update_xaxes(matches='x')
        fig.update_yaxes(matches='y')
    
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(height=800, margin=dict(l=10, r=10, t=50, b=10))

    return fig

# --- 4. MAIN APP ---
def main():
    st.title("🚀 CFD Pro Viewer v7 (Fast Scroll)")

    with st.sidebar:
        st.header("1. Job Selection")
        if os.path.exists(OPENFOAM_BASE_DIR):
            base_path = OPENFOAM_BASE_DIR
            available_jobs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
        else:
            base_path = "." # Fallback for local testing
            available_jobs = sorted([d for d in os.listdir(".") if os.path.isdir(d)])

        if not available_jobs: st.stop()
        
        selected_job = st.selectbox("Select Job", available_jobs)
        cases_root = os.path.join(base_path, selected_job, "CASES")
        
        if not os.path.exists(cases_root): st.stop()
        
        all_cases = sorted([d for d in os.listdir(cases_root) if d.isdigit() and len(d)==3])
        
        # Mode Selection
        mode = st.radio("Display Mode", ["Side-by-Side", "Grid View"]) # Removed Blink for animation simplicity
        
        if mode == "Grid View":
            selected_cases = st.multiselect("Select Cases", all_cases, default=all_cases[:4] if len(all_cases)>=4 else all_cases)
        else:
            c1 = st.selectbox("Case A", all_cases, index=0)
            c2_idx = 1 if len(all_cases) > 1 else 0
            c2 = st.selectbox("Case B", all_cases, index=c2_idx)
            selected_cases = [c1, c2]
            
        if not selected_cases: st.stop()

        # Variable Selection
        img_path = os.path.join(cases_root, selected_cases[0], "postProcessing", "images")
        if os.path.exists(img_path):
            avail_vars = sorted([d for d in os.listdir(img_path) if os.path.isdir(os.path.join(img_path, d))])
            variable = st.selectbox("Variable", avail_vars)
        else: st.stop()

    # Load Data
    dataset = load_data_into_ram(cases_root, selected_cases, variable)

    with st.sidebar:
        st.header("2. View Controls")
        master_case = selected_cases[0]
        available_views = sorted(list(dataset[master_case].keys()))
        view_selection = st.selectbox("Camera View", available_views)
        
        # Check sequence length
        num_frames = len(dataset[master_case][view_selection])
        st.info(f"Sequence Length: {num_frames} frames")
        st.caption("Slider is now located below the image for instant scrolling.")

    # Prepare Data for Animation
    # We need a list of images for every case
    data_sequences = {}
    for case in selected_cases:
        if case in dataset and view_selection in dataset[case]:
            # Extract just the PIL images from the (id, img) tuples
            data_sequences[case] = [item[1] for item in dataset[case][view_selection]]
        else:
            data_sequences[case] = []

    # Check if we actually have data
    if not data_sequences[selected_cases[0]]:
        st.error("No images found for this view.")
        st.stop()

    # Render
    # Note: We pass the WHOLE sequence, not just one frame
    with st.spinner("Building Animation Bundle... (This may take a moment)"):
        fig = render_animated_plot(data_sequences, selected_cases, mode)
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
