import streamlit as st
import os
import re
import numpy as np
from PIL import Image
import io
import math

# ---------------- CONFIG ----------------
st.set_page_config(layout="wide", page_title="CFD Case Viewer")

OPENFOAM_BASE_DIR = "/home/openfoam/openFoam/run"
MAX_DISPLAY_WIDTH = 1200
Image.MAX_IMAGE_PIXELS = None

# ---------------- SESSION STATE ----------------
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

if "active_blink_case" not in st.session_state:
    st.session_state.active_blink_case = None

# Blink image cache for instant switching
if "blink_cache" not in st.session_state:
    st.session_state.blink_cache = {}


def reset_state():
    st.session_state.data_loaded = False
    st.session_state.active_blink_case = None
    st.session_state.blink_cache = {}


# ---------------- METADATA PARSER ----------------
def parse_metadata(filename):
    name_no_ext = os.path.splitext(filename)[0]
    parts = name_no_ext.split("_")
    metadata = {"view": "Default", "sort_key": 0}

    metadata["view"] = parts[3] if len(parts) > 3 else parts[-1]

    match = re.search(r"(\d{6})", name_no_ext)
    if match:
        metadata["sort_key"] = int(match.group(1))
    else:
        nums = re.findall(r"\d+", name_no_ext)
        if nums:
            metadata["sort_key"] = int(nums[-1])

    return metadata


# ---------------- LOAD IMAGE METADATA ONLY ----------------
@st.cache_data(show_spinner=False)
def load_image_metadata(root_dir, selected_cases, variable_folder):
    dataset = {}

    for case in selected_cases:
        path = os.path.join(
            root_dir, case, "postProcessing", "images", variable_folder
        )
        if not os.path.exists(path):
            continue

        dataset[case] = {}
        files = [
            f for f in os.listdir(path)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        for f in files:
            meta = parse_metadata(f)
            view = meta["view"]

            if view not in dataset[case]:
                dataset[case][view] = []

            full_path = os.path.join(path, f)
            dataset[case][view].append((meta["sort_key"], full_path))

        for view in dataset[case]:
            dataset[case][view].sort(key=lambda x: x[0])

    return dataset


# ---------------- LOAD + RESIZE ----------------
def load_and_resize_image(path):
    img = Image.open(path).convert("RGB")

    if img.width > MAX_DISPLAY_WIDTH:
        ratio = MAX_DISPLAY_WIDTH / float(img.width)
        new_height = int(img.height * ratio)
        img = img.resize(
            (MAX_DISPLAY_WIDTH, new_height),
            Image.Resampling.BILINEAR,
        )

    return np.array(img)


# ---------------- GRID CREATOR ----------------
def create_combined_grid(images_dict, cols=3):
    pil_images = [Image.fromarray(img) for img in images_dict.values()]
    if not pil_images:
        return None

    rows = math.ceil(len(pil_images) / cols)
    img_w, img_h = pil_images[0].size

    grid_img = Image.new("RGB", (cols * img_w, rows * img_h), (20, 20, 20))

    for idx, img in enumerate(pil_images):
        row = idx // cols
        col = idx % cols
        grid_img.paste(img, (col * img_w, row * img_h))

    buffer = io.BytesIO()
    grid_img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def create_blink_gif(img_a, img_b, duration=400, max_width=600):
    pil_a = Image.fromarray(img_a).convert("RGB")
    pil_b = Image.fromarray(img_b).convert("RGB")

    # ----- Create shared palette -----
    combined = Image.new(
        "RGB",
        (pil_a.width, pil_a.height * 2)
    )
    combined.paste(pil_a, (0, 0))
    combined.paste(pil_b, (0, pil_a.height))

    palette_image = combined.convert(
        "P",
        palette=Image.ADAPTIVE,
        colors=256
    )

    # Apply SAME palette to both frames
    pil_a_p = pil_a.quantize(palette=palette_image)
    pil_b_p = pil_b.quantize(palette=palette_image)

    frames = []
    for _ in range(6):
        frames.append(pil_a_p)
        frames.append(pil_b_p)

    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=False,
        disposal=2,
    )

    buffer.seek(0)
    return buffer


def main():
    st.title("CFD Case Viewer")

    # ===== SIDEBAR =====
    with st.sidebar:
        st.header("Job Selection")

        base_path = OPENFOAM_BASE_DIR if os.path.exists(OPENFOAM_BASE_DIR) else "."
        available_jobs = sorted(
            [d for d in os.listdir(base_path)
             if os.path.isdir(os.path.join(base_path, d))]
        )

        selected_job = st.selectbox(
            "Select Job / Run",
            available_jobs,
            index=None,
            on_change=reset_state,
        )

        if not selected_job:
            st.stop()

        cases_root_path = os.path.join(base_path, selected_job, "CASES")

        all_cases = sorted(
            [d for d in os.listdir(cases_root_path)
             if os.path.isdir(os.path.join(cases_root_path, d))
             and d.isdigit() and len(d) == 3]
        )

        st.header("Configuration")

        mode = st.radio(
            "Display Mode",
            ["Side-by-Side", "Grid View", "Blink Comparator"],
            on_change=reset_state,
        )

        selected_cases = []

        if mode == "Grid View":
            selected_cases = st.multiselect(
                "Select Cases",
                all_cases,
                on_change=reset_state,
            )
        else:
            col1, col2 = st.columns(2)
            c1 = col1.selectbox("Case A", all_cases, on_change=reset_state)
            c2 = col2.selectbox("Case B", all_cases, on_change=reset_state)
            if c1 and c2:
                selected_cases = [c1, c2]

        if not selected_cases:
            st.stop()

        master_case = all_cases[0]
        img_path = os.path.join(
            cases_root_path, master_case, "postProcessing", "images"
        )

        avail_vars = sorted(
            [d for d in os.listdir(img_path)
             if os.path.isdir(os.path.join(img_path, d))]
        )

        variable = st.selectbox(
            "Variable",
            avail_vars,
            index=None,
            on_change=reset_state,
        )

        if not variable:
            st.stop()

        st.divider()

        if not st.session_state.data_loaded:
            if st.button("LOAD DATA 🚀"):
                st.session_state.data_loaded = True
                st.rerun()
            else:
                st.stop()

    # ===== LOAD METADATA =====
    dataset = load_image_metadata(
        cases_root_path, selected_cases, variable
    )

    # ===== COMMON VIEWS (FIXED) =====
    common_views = None
    for case in selected_cases:
        case_views = set(dataset[case].keys())
        if common_views is None:
            common_views = case_views
        else:
            common_views = common_views.intersection(case_views)

    if not common_views:
        st.error("No common camera views found across selected cases.")
        st.stop()

    # ===== VIEW CONTROLS =====
    with st.sidebar:
        st.header("View Controls")

        available_views = sorted(list(common_views))
        view_selection = st.selectbox("Camera View", available_views)

        master_images = dataset[selected_cases[0]][view_selection]
        frame_index = 0

        if len(master_images) > 1:
            frame_index = st.slider(
                "Frame Position", 0, len(master_images) - 1, 0
            )

    st.markdown("### Visualization")

    # =======================
    # BLINK MODE (Instant)
    # =======================
    if mode == "Blink Comparator":

        case_a, case_b = selected_cases

        cache_key = (case_a, case_b, view_selection, frame_index)

        if cache_key not in st.session_state.blink_cache:

            blink_images = {}

            for case in selected_cases:
                case_imgs = dataset[case][view_selection]
                idx = min(frame_index, len(case_imgs) - 1)
                _, path = case_imgs[idx]
                blink_images[case] = load_and_resize_image(path)

            st.session_state.blink_cache[cache_key] = blink_images

        blink_images = st.session_state.blink_cache[cache_key]

        if st.session_state.active_blink_case is None:
            st.session_state.active_blink_case = case_a

        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔁 Switch Case"):
                st.session_state.active_blink_case = (
                    case_b
                    if st.session_state.active_blink_case == case_a
                    else case_a
                )

        with col2:
            generate_gif = st.button("🎞 Generate Blink GIF")

        active_case = st.session_state.active_blink_case

        st.subheader(f"Active: {active_case}")
        st.image(blink_images[active_case], use_container_width=True)

        if generate_gif:
            gif_buffer = create_blink_gif(
                blink_images[case_a],
                blink_images[case_b],
            )

            st.download_button(
                "⬇ Download Blink GIF",
                gif_buffer,
                f"blink_{case_a}_{case_b}.gif",
                "image/gif",
            )

        return

    # =======================
    # SIDE-BY-SIDE
    # =======================
    if mode == "Side-by-Side":

        images = {}
        for case in selected_cases:
            case_imgs = dataset[case][view_selection]
            idx = min(frame_index, len(case_imgs) - 1)
            _, path = case_imgs[idx]
            images[case] = load_and_resize_image(path)

        cols = st.columns(len(images))
        for i, case in enumerate(images):
            with cols[i]:
                st.subheader(case)
                st.image(images[case], use_container_width=True)

    # =======================
    # GRID MODE
    # =======================
    if mode == "Grid View":

        images = {}
        for case in selected_cases:
            case_imgs = dataset[case][view_selection]
            idx = min(frame_index, len(case_imgs) - 1)
            _, path = case_imgs[idx]
            images[case] = load_and_resize_image(path)

        cols = 3
        grid_columns = st.columns(cols)

        for i, case in enumerate(images):
            with grid_columns[i % cols]:
                st.subheader(case)
                st.image(images[case], use_container_width=True)

                buffer = io.BytesIO()
                Image.fromarray(images[case]).save(buffer, format="PNG")
                buffer.seek(0)

                st.download_button(
                    "⬇ Download Image",
                    buffer,
                    f"{case}.png",
                    "image/png",
                    key=f"dl_{case}",
                )

        st.markdown("---")

        if st.button("⬇ Download Combined Grid"):
            grid_buffer = create_combined_grid(images, cols=cols)
            st.download_button(
                "Download Grid Image",
                grid_buffer,
                "combined_grid.png",
                "image/png",
            )


if __name__ == "__main__":
    main()
