# NEEZY cloud candidate training

Import `NEEZY_cloud_training.ipynb` in Kaggle or Colab. Add `HF_TOKEN`,
`HF_MODEL_REPO`, and `HF_DATASET_REPO` to the platform's secret manager, then Run All.
The notebook trains and backtests on cloud data and uploads candidate JSON plus the
public-candle dataset with `huggingface_hub.upload_file`.

It never connects to a broker and never updates HF `latest/`. Use the PC's no-order
`paper_candidate` mode for exact-hash virtual validation, then run
`scripts/promote_model.py` with the generated report as documented in
`docs/CLOUD_OPERATIONS.md`. Replace `YOUR_USERNAME` in `kernel-metadata.json` before
`kaggle kernels push -p kaggle/cloud` from the repository root.

The current compact model uses CPU; Kaggle/Colab sessions still expire and are not an
always-on executor. Full setup, secrets, validation gates, and warnings are in
[`../../docs/CLOUD_OPERATIONS.md`](../../docs/CLOUD_OPERATIONS.md).
