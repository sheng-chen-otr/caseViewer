import streamlit as st
import os
import re
import math
from PIL import Image
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="CFD Pro Viewer v6.2")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    div[data-testid="stSidebar"] { background-color: #262730; }
    h1 { color: #FAFAFA; }
    .stProgress > div > div > div > div { background-color: #00ADB5; }
    
    /* Load Button Styling */
    div.stButton > button:first-child {
        background-color: #00ADB5;
        color: white;
        font-weight: bold;
        border: none;
        width: 100%;
        margin-top: 10px;
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
    """Callback: Resets the load state if user changes any input"""
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

# --- 2. DATA LOADING (RAM CACHE) ---
@st.cache_resource(show_spinner=False)
def load_data_into_ram(root_dir, selected_cases, variable_folder):
    dataset = {}
    MAX_WIDTH = 1200  
    
    progress_bar = st.progress(0, text="Initializing Data Loader...")
    total_steps = len(selected_cases)
    
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
                
                # --- DOWNSAMPLE FOR DISPLAY ---
                if img.width > MAX_WIDTH:
                    ratio = MAX_WIDTH / float(img.width)
                    new_height = int((float(img.height) * float(ratio)))
                    # Create a copy for display, keep original on disk
                    img_display = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
                else:
                    img_display = img

                # STORE: (SortKey, DisplayImage, OriginalFilePath)
                dataset[case][view].append((meta['sort_key'], img_display, full_path))
                
            except Exception as e:
                print(f"Skipping corrupt file {f}: {e}")

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
            buttons.append(dict(label=f"Show {case}", method="update", 
                              args=[{"visible": vis_list}, {"title": f"Active View: {case}"}]))
            
        fig.update_layout(updatemenus=[dict(type="buttons", direction="right", x=0.5, y=1.15, buttons=buttons)],
                          title_text=f"Active View: {titles[0]}")

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
    st.title("🚀 CFD Pro Viewer v6.2")

    # --- SIDEBAR: SELECTION ---
    with st.sidebar:
        st.header("1. Job Selection")
        
        if os.path.exists(OPENFOAM_BASE_DIR):
            base_path = OPENFOAM_BASE_DIR
            available_jobs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
        else:
            base_path = "."
            available_jobs = sorted([d for d in os.listdir(".") if os.path.isdir(d)])

        selected_job = st.selectbox("Select Job / Run", available_jobs, 
                                  index=None, placeholder="Choose a job...", on_change=reset_state)
        
        if not selected_job: st.stop()

        cases_root_path = os.path.join(base_path, selected_job, "CASES")
        if not os.path.exists(cases_root_path):
            st.error(f"Directory not found: {cases_root_path}")
            st.stop()

        all_cases = sorted([d for d in os.listdir(cases_root_path) 
                            if os.path.isdir(os.path.join(cases_root_path, d)) 
                            and d.isdigit() and len(d)==3])
        
        if not all_cases: st.error("No cases found."); st.stop()

        st.header("2. Configuration")
        mode = st.radio("Display Mode", ["Side-by-Side", "Grid View", "Blink Comparator"], on_change=reset_state)
        
        selected_cases = []
        if mode == "Grid View":
            selected_cases = st.multiselect("Select Cases", all_cases, 
                                          default=[], placeholder="Select cases...", on_change=reset_state)
        else:
            col1, col2 = st.columns(2)
            c1 = col1.selectbox("Case A", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            c2 = col2.selectbox("Case B", all_cases, index=None, placeholder="Select...", on_change=reset_state)
            if c1 and c2: selected_cases = [c1, c2]

        if not selected_cases: st.info("Please select cases to proceed."); st.stop()

        master_structure_case = all_cases[0]
        img_path = os.path.join(cases_root_path, master_structure_case, "postProcessing", "images")
        
        avail_vars = []
        if os.path.exists(img_path):
            avail_vars = sorted([d for d in os.listdir(img_path) if os.path.isdir(os.path.join(img_path, d))])

        variable = st.selectbox("Variable", avail_vars, 
                              index=None, placeholder="Choose variable...", key="var_select", on_change=reset_state)

        if not variable: st.stop()

        st.divider()

        if not st.session_state.data_loaded:
            if st.button("LOAD DATA 🚀"):
                st.session_state.data_loaded = True
                st.rerun()
            else:
                st.stop()

    # --- DATA LOADING ---
    dataset = load_data_into_ram(cases_root_path, selected_cases, variable)
    
    if not dataset: st.error("Could not load images."); st.stop()

    # --- VIEW CONTROLS ---
    with st.sidebar:
        st.header("3. View Controls")
        
        master_case = selected_cases[0]
        if master_case not in dataset: st.error("Master case failed."); st.stop()
            
        available_views = sorted(list(dataset[master_case].keys()))
        view_selection = st.selectbox("Camera View", available_views)
        
        master_images = dataset[master_case][view_selection]
        num_frames = len(master_images)
        
        frame_index = 0
        if num_frames > 1:
            st.info(f"Loaded {num_frames} frames.")
            frame_index = st.slider("Sequence Position", 0, num_frames - 1, 0)
            current_id = master_images[frame_index][0]
            st.caption(f"Sort Key: {current_id}")

    # --- PREPARE DATA FOR PLOT & DOWNLOAD ---
    images_to_plot = {}
    download_paths = {}

    for case in selected_cases:
        if case in dataset and view_selection in dataset[case]:
            case_imgs = dataset[case][view_selection]
            # Safety clamp for index
            idx = min(frame_index, len(case_imgs) - 1)
            
            # UNPACK: (SortKey, DisplayImage, FullPath)
            _, display_img, full_path = case_imgs[idx]
            
            images_to_plot[case] = display_img
            download_paths[case] = full_path
        else:
            images_to_plot[case] = None
            download_paths[case] = None

    # --- RENDER PLOT ---
    fig = render_plot(images_to_plot, mode)
    st.plotly_chart(fig, use_container_width=True)

    # --- DOWNLOAD BUTTONS ---
    st.markdown("---")
    st.subheader("📥 Download Full Resolution Images")
    
    # Create a column for each case to keep buttons aligned with the images (roughly)
    cols = st.columns(len(selected_cases))
    
    for i, case in enumerate(selected_cases):
        with cols[i]:
            path = download_paths[case]
            if path and os.path.exists(path):
                file_name = os.path.basename(path)
                
                # Open the original 4K file from disk
                with open(path, "rb") as f:
                    st.download_button(
                        label=f"💾 Download {case}",
                        data=f,
                        file_name=file_name,
                        mime="image/png",
                        key=f"dl_{case}_{frame_index}"
                    )
            else:
                st.warning(f"No file for {case}")

if __name__ == "__main__":
    main()
