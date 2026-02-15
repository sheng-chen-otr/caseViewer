import streamlit as st
import os
import re
import math
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="CFD Pro Viewer v9")

st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
    div.stButton > button:first-child {
        background-color: #00ADB5;
        color: white;
        font-weight: bold;
        border: none;
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS ---
OPENFOAM_BASE_DIR = "/home/openfoam/openFoam/run"

# --- STATE MANAGEMENT ---
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

def reset_state():
    """Callback to reset the view if user changes filter settings"""
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

# --- 2. DATA LOADING ---
@st.cache_resource(show_spinner=False)
def load_data_into_ram(root_dir, selected_cases, variable_folder):
    dataset = {}
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

# --- 3. ANIMATION ENGINE ---
def render_animated_plot(data_sequences, case_names, mode, sync=True):
    """
    Handles both Grid View (Subplots) and Blink Comparator (Single Plot + Toggles)
    """
    master_len = len(data_sequences[case_names[0]])
    frames = []
    
    # --- MODE A: BLINK COMPARATOR ---
    if mode == "Blink Comparator":
        # Single Plot
        fig = make_subplots(rows=1, cols=1)
        
        # Add Initial Traces (Time 0)
        # Trace 0 = Case A (Visible)
        # Trace 1 = Case B (Hidden)
        img_a_0 = data_sequences[case_names[0]][0] if data_sequences[case_names[0]] else None
        img_b_0 = data_sequences[case_names[1]][0] if data_sequences[case_names[1]] else None
        
        fig.add_trace(go.Image(z=img_a_0, name=case_names[0], visible=True))
        fig.add_trace(go.Image(z=img_b_0, name=case_names[1], visible=False))

        # Build Frames (Update BOTH traces for every time step)
        for k in range(master_len):
            # Get image for Case A at step k
            img_a = data_sequences[case_names[0]][min(k, len(data_sequences[case_names[0]])-1)]
            # Get image for Case B at step k
            img_b = data_sequences[case_names[1]][min(k, len(data_sequences[case_names[1]])-1)]
            
            # The frame updates data for Trace 0 AND Trace 1
            frames.append(go.Frame(data=[go.Image(z=img_a), go.Image(z=img_b)], name=str(k)))

        # Add Blink Buttons
        buttons = [
            dict(label=f"Show {case_names[0]}", 
                 method="update", 
                 args=[{"visible": [True, False]}, {"title": f"View: {case_names[0]}"}]),
            dict(label=f"Show {case_names[1]}", 
                 method="update", 
                 args=[{"visible": [False, True]}, {"title": f"View: {case_names[1]}"}])
        ]
        
        fig.update_layout(
            updatemenus=[dict(type="buttons", direction="right", x=0.5, y=1.15, buttons=buttons)],
            title_text=f"View: {case_names[0]}"
        )

    # --- MODE B: GRID / SIDE-BY-SIDE ---
    else:
        n_plots = len(case_names)
        cols = 2 if n_plots < 4 else 3
        rows = math.ceil(n_plots / cols)
        
        fig = make_subplots(rows=rows, cols=cols, subplot_titles=case_names, 
                            horizontal_spacing=0.01, vertical_spacing=0.05)
        
        # Initial Traces
        idx = 0
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                if idx < n_plots:
                    case = case_names[idx]
                    first_img = data_sequences[case][0] if data_sequences[case] else None
                    fig.add_trace(go.Image(z=first_img), row=r, col=c)
                    idx += 1

        # Build Frames
        for k in range(master_len):
            frame_data = []
            for case in case_names:
                seq = data_sequences[case]
                img_idx = min(k, len(seq)-1)
                frame_data.append(go.Image(z=seq[img_idx]))
            frames.append(go.Frame(data=frame_data, name=str(k)))
            
        if sync:
            fig.update_xaxes(matches='x')
            fig.update_yaxes(matches='y')

    # --- COMMON ANIMATION CONTROLS ---
    fig.frames = frames

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
    
    # Common Polish
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(height=800, margin=dict(l=10, r=10, t=50, b=10))

    return fig

# --- 4. MAIN APP ---
def main():
    st.title("🚀 CFD Pro Viewer v9")

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("1. Job Selection")
        
        if os.path.exists(OPENFOAM_BASE_DIR):
            base_path = OPENFOAM_BASE_DIR
            available_jobs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
        else:
            base_path = "." 
            available_jobs = sorted([d for d in os.listdir(".") if os.path.isdir(d)])

        selected_job = st.selectbox("Select Job", available_jobs, 
                                  index=None, placeholder="Choose a job...", on_change=reset_state)
        
        if not selected_job: st.stop()

        cases_root = os.path.join(base_path, selected_job, "CASES")
        if not os.path.exists(cases_root): st.stop()
        
        all_cases = sorted([d for d in os.listdir(cases_root) if d.isdigit() and len(d)==3])
        
        # Added Blink Comparator back to options
        mode = st.radio("Display Mode", ["Side-by-Side", "Grid View", "Blink Comparator"], on_change=reset_state)
        
        selected_cases = []
        if mode == "Grid View":
            selected_cases = st.multiselect("Select Cases", all_cases, default=[], placeholder="Select cases...", on_change=reset_state)
        else:
            # Side-by-Side OR Blink Comparator (Both need exactly 2 cases usually)
            col1, col2 = st.columns(2)
            c1 = col1.selectbox("Case A", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            c2 = col2.selectbox("Case B", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            if c1 and c2: selected_cases = [c1, c2]

        if not selected_cases: st.stop()

        img_path = os.path.join(cases_root, selected_cases[0], "postProcessing", "images")
        if os.path.exists(img_path):
            avail_vars = sorted([d for d in os.listdir(img_path) if os.path.isdir(os.path.join(img_path, d))])
            variable = st.selectbox("Variable", avail_vars, index=None, placeholder="Choose variable...", on_change=reset_state)
        else: st.stop()

        if not variable: st.stop()

        st.divider()
        
        if not st.session_state.data_loaded:
            if st.button("LOAD DATA 🚀"):
                st.session_state.data_loaded = True
                st.rerun()
            else:
                st.stop()

    # --- EXECUTION ---
    dataset = load_data_into_ram(cases_root, selected_cases, variable)

    with st.sidebar:
        st.header("2. View Controls")
        master_case = selected_cases[0]
        if master_case not in dataset: st.stop()

        available_views = sorted(list(dataset[master_case].keys()))
        view_selection = st.selectbox("Camera View", available_views)
        st.success(f"Loaded {len(dataset[master_case][view_selection])} frames.")

    data_sequences = {}
    for case in selected_cases:
        if case in dataset and view_selection in dataset[case]:
            data_sequences[case] = [item[1] for item in dataset[case][view_selection]]
        else:
            data_sequences[case] = []

    if not data_sequences[selected_cases[0]]: st.stop()

    with st.spinner("Generating Animation..."):
        fig = render_animated_plot(data_sequences, selected_cases, mode)
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
