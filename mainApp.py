import streamlit as st
import os
import re
import math
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="CFD Pro Viewer v6")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
    .stProgress > div > div > div > div { background-color: #00ADB5; }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS ---
# The absolute path to the OpenFOAM run directory
OPENFOAM_BASE_DIR = "/home/openfoam/openFoam/run"

# --- 1. PARSING LOGIC ---
def parse_metadata(filename):
    """
    Extracts View (4th element) and Sort Key (6-digit number).
    """
    name_no_ext = os.path.splitext(filename)[0]
    parts = name_no_ext.split('_')
    
    metadata = {
        'view': 'Default',
        'sort_key': 0,
        'filename': filename
    }

    # RULE: 4th element (index 3) is the View Angle
    if len(parts) > 3:
        metadata['view'] = parts[3]
    else:
        metadata['view'] = parts[-1]

    # RULE: Find 6-digit number for sorting
    match = re.search(r'(\d{6})', name_no_ext)
    if match:
        metadata['sort_key'] = int(match.group(1))
    else:
        nums = re.findall(r'\d+', name_no_ext)
        if nums:
            metadata['sort_key'] = int(nums[-1])

    return metadata

# --- 2. DATA LOADING (RAM CACHE) ---
@st.cache_resource(show_spinner=False)
def load_data_into_ram(root_dir, selected_cases, variable_folder):
    """
    Loads images, DOWNSAMPLES to 1200px immediately.
    """
    dataset = {}
    MAX_WIDTH = 1200  # Hard constraint for performance
    
    progress_bar = st.progress(0, text="Initializing Data Loader...")
    total_steps = len(selected_cases)
    
    for i, case in enumerate(selected_cases):
        # Path construction: root_dir is now .../<JOB>/CASES
        path = os.path.join(root_dir, case, "postProcessing", "images", variable_folder)
        
        if not os.path.exists(path):
            continue

        dataset[case] = {}
        
        files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        for f in files:
            meta = parse_metadata(f)
            view = meta['view']
            
            if view not in dataset[case]:
                dataset[case][view] = []
            
            try:
                full_path = os.path.join(path, f)
                img = Image.open(full_path)
                
                # --- DOWNSAMPLING ---
                if img.width > MAX_WIDTH:
                    ratio = MAX_WIDTH / float(img.width)
                    new_height = int((float(img.height) * float(ratio)))
                    img = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
                # --------------------

                dataset[case][view].append((meta['sort_key'], img))
                
            except Exception as e:
                print(f"Skipping corrupt file {f}: {e}")

        # Sort by Sequence ID
        for view in dataset[case]:
            dataset[case][view].sort(key=lambda x: x[0])

        progress_bar.progress((i + 1) / total_steps, text=f"Processed Case {case}")

    progress_bar.empty()
    return dataset

# --- 3. VISUALIZATION ENGINE ---
def render_plot(images_map, mode, sync=True):
    titles = list(images_map.keys())
    n_plots = len(titles)
    
    if n_plots == 0: return go.Figure()

    if mode == "Blink Comparator":
        fig = make_subplots(rows=1, cols=1)
        for i, (case, img) in enumerate(images_map.items()):
            visible = True if i == 0 else False
            fig.add_trace(go.Image(z=img, name=case, visible=visible, opacity=1))
        
        buttons = []
        for i, case in enumerate(titles):
            vis_list = [False] * n_plots
            vis_list[i] = True
            buttons.append(dict(
                label=f"Show {case}", 
                method="update", 
                args=[{"visible": vis_list}, {"title": f"Active View: {case}"}]
            ))
            
        fig.update_layout(
            updatemenus=[dict(type="buttons", direction="right", x=0.5, y=1.15, buttons=buttons)],
            title_text=f"Active View: {titles[0]}"
        )

    else:
        cols = 2 if n_plots < 4 else 3
        rows = math.ceil(n_plots / cols)
        fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles, 
                            horizontal_spacing=0.01, vertical_spacing=0.05)
        
        idx = 0
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                if idx < n_plots:
                    case = titles[idx]
                    fig.add_trace(go.Image(z=images_map[case]), row=r, col=c)
                    idx += 1
        
        if sync:
            fig.update_xaxes(matches='x')
            fig.update_yaxes(matches='y')

    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False, scaleanchor="x")
    fig.update_layout(height=800, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# --- 4. MAIN APPLICATION ---
def main():
    st.title("🚀 CFD Pro Viewer v6")

    # --- SIDEBAR: JOB SELECTION ---
    with st.sidebar:
        st.header("1. Job Selection")
        
        # Check if environment path exists (Development Safety Net)
        if os.path.exists(OPENFOAM_BASE_DIR):
            base_path = OPENFOAM_BASE_DIR
            # Get list of folders in the run directory
            available_jobs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
        else:
            st.warning(f"Path `{OPENFOAM_BASE_DIR}` not found. Using local directory.")
            base_path = "."
            available_jobs = sorted([d for d in os.listdir(".") if os.path.isdir(d)])

        if not available_jobs:
            st.error("No Job folders found.")
            st.stop()

        # JOB DROPDOWN
        selected_job = st.selectbox("Select Job / Run", available_jobs)
        
        # Construct the path to the CASES folder
        # Path: /home/.../run/<JOB>/CASES
        cases_root_path = os.path.join(base_path, selected_job, "CASES")
        
        if not os.path.exists(cases_root_path):
            st.error(f"Directory not found: {cases_root_path}")
            st.info("Expected structure: <JOB_FOLDER>/CASES/<CASE_ID>")
            st.stop()

        # Find Cases (3-digit folders) inside the CASES directory
        all_cases = sorted([d for d in os.listdir(cases_root_path) 
                            if os.path.isdir(os.path.join(cases_root_path, d)) 
                            and d.isdigit() and len(d)==3])
        
        if not all_cases:
            st.error(f"No 3-digit case folders found in {selected_job}/CASES")
            st.stop()

        # --- MODE & CASE SELECTION ---
        st.header("2. Configuration")
        mode = st.radio("Display Mode", ["Side-by-Side", "Grid View", "Blink Comparator"])
        
        if mode == "Grid View":
            selected_cases = st.multiselect("Select Cases", all_cases, default=all_cases[:4] if len(all_cases)>=4 else all_cases)
        else:
            c1 = st.selectbox("Case A (Master)", all_cases, index=0)
            c2_idx = 1 if len(all_cases) > 1 else 0
            c2 = st.selectbox("Case B", all_cases, index=c2_idx)
            selected_cases = [c1, c2]

        if not selected_cases: st.stop()

        # --- VARIABLE SELECTION ---
        # Scan Master Case
        img_path = os.path.join(cases_root_path, selected_cases[0], "postProcessing", "images")
        if os.path.exists(img_path):
            avail_vars = sorted([d for d in os.listdir(img_path) if os.path.isdir(os.path.join(img_path, d))])
            variable = st.selectbox("Variable", avail_vars)
        else:
            st.error(f"No 'postProcessing/images' folder in Case {selected_cases[0]}")
            st.stop()

    # --- LOAD DATA ---
    dataset = load_data_into_ram(cases_root_path, selected_cases, variable)
    
    if not dataset:
        st.error("Could not load images.")
        st.stop()

    # --- VIEW CONTROLS ---
    with st.sidebar:
        st.header("3. View Controls")
        
        master_case = selected_cases[0]
        if master_case not in dataset:
            st.error("Master case failed to load.")
            st.stop()
            
        available_views = sorted(list(dataset[master_case].keys()))
        
        if not available_views:
            st.warning("No valid views found.")
            st.stop()
            
        view_selection = st.selectbox("Camera View", available_views)
        
        master_images = dataset[master_case][view_selection]
        num_frames = len(master_images)
        
        frame_index = 0
        if num_frames > 1:
            st.info(f"Loaded {num_frames} frames.")
            frame_index = st.slider("Sequence Position", 0, num_frames - 1, 0)
            current_id = master_images[frame_index][0]
            st.caption(f"Sort Key: {current_id}")

    # --- RENDER ---
    images_to_plot = {}
    for case in selected_cases:
        if case in dataset and view_selection in dataset[case]:
            case_imgs = dataset[case][view_selection]
            idx = min(frame_index, len(case_imgs) - 1)
            images_to_plot[case] = case_imgs[idx][1]
        else:
            images_to_plot[case] = None

    fig = render_plot(images_to_plot, mode)
    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
