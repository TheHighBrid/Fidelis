# Bootstrap the macOS arm64 native preview

This creates a **new isolated runtime home**, using pinned local archives and the
cleared RealeSR-general-v3 model. It never replaces an existing home or modifies
the normal installation. The source preview, compatible Python/macOS and Python
dependencies are separate prerequisites; see [offline Python setup](OFFLINE_PYTHON.md).
This is the verified preview path, distinct from the historical macOS installer
which also stages the unresolved DF2K model.

Prepare the inputs while free downloads are available. Keep this cache outside
the source checkout so binary assets cannot enter a later source archive:

```bash
preview_cache="$HOME/fidelis-preview-inputs"
mkdir -p "$preview_cache/archives" "$preview_cache/models/models-RealeSR-general-v3"
curl -fL 'https://github.com/nihui/realsr-ncnn-vulkan/releases/download/20220728/realsr-ncnn-vulkan-20220728-macos.zip' \
  -o "$preview_cache/archives/realsr-ncnn-vulkan-20220728-macos.zip"
curl -fL 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip' \
  -o "$preview_cache/archives/realesrgan-ncnn-vulkan-20220424-macos.zip"
curl -fL 'https://huggingface.co/tumuyan2/realsr-models/resolve/0fe68041370150c7695816e229dc982bfc06ed58/models-RealeSR-general-v3/x4.param?download=true' \
  -o "$preview_cache/models/models-RealeSR-general-v3/x4.param"
curl -fL 'https://huggingface.co/tumuyan2/realsr-models/resolve/0fe68041370150c7695816e229dc982bfc06ed58/models-RealeSR-general-v3/x4.bin?download=true' \
  -o "$preview_cache/models/models-RealeSR-general-v3/x4.bin"
```

Transfer that cache and the source preview to the target. On macOS arm64, choose
a home that does not exist, then run from the extracted application:

```bash
preview_runtime_home="$HOME/fidelis-preview-runtime"
python3.12 scripts/bootstrap-macos-preview.py \
  --archive-dir "$preview_cache/archives" \
  --model-cache "$preview_cache/models" \
  --runtime-home "$preview_runtime_home"
```

The bootstrap itself uses only local files. It checks the catalog's archive,
selected executable and notice hashes; stages only the selected executables;
copies model weights only when their terms and hashes match; and registers the
single supported RealeSR model. Bundled DF2K and other unapproved weights are not
installed. It does not extract arbitrary ZIP members. Required source notices are
copied into `runtime/NOTICES` and the model folder.

All files are prepared in a sibling staging directory. macOS exclusive rename
publishes the home only after verification and refuses even a concurrently
created empty destination. Failure removes only the unpublished staging area.
Keep `native-preview-receipt.json` and `install.json` in the resulting home.
Their `native_execution_verified: false` is deliberate: staging hashes does not
prove inference, image quality or release acceptance.

After the Python environment is ready, point this application session at the new
home and select its supported model:

```bash
export FIDELIS_HOME="$preview_runtime_home"
export FIDELIS_MODEL=RealeSR-general-v3
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 --port 8765
```

Choose `Fast_Fidelity` with `RealeSR-general-v3`. Region editing still takes
aligned base/texture passes. The preview dispatcher supports that model at 4×;
it is not a replacement for every legacy model/runtime combination. Separate
actual workflow receipts establish execution on the recorded M1. Human visual,
physical mobile, broader corpus, SDXL and final release gates remain open.
