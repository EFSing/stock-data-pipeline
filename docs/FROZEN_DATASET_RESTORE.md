# Frozen DEVELOPMENT_EXPOSED Dataset v2 Restore

Release/tag: `frozen-development-dataset-2026-08-28-v2`  
Release URL: https://github.com/EFSing/stock-data-pipeline/releases/tag/frozen-development-dataset-2026-08-28-v2  
Archive: `stock-data-pipeline-frozen-development-v2.zip`  
Dataset version: `SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2`  
Manifest SHA-256: `sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216`  
Archive SHA-256: `sha256:15e3c63da65cd1eba52ecd6d441be22d6556e9ae2008f70c652a01bb7b0eaeb2`  
Expected restore path: `artifacts/development_strategy_stability_v2/`

From the repository root, download the release assets:

```bash
gh release download frozen-development-dataset-2026-08-28-v2 \
  --repo EFSing/stock-data-pipeline \
  --pattern stock-data-pipeline-frozen-development-v2.zip \
  --pattern FROZEN_ARCHIVE_SHA256SUMS.txt \
  --pattern FROZEN_ARCHIVE_METADATA.json
```

Verify the archive SHA-256 (PowerShell):

```powershell
(Get-FileHash -Algorithm SHA256 .\stock-data-pipeline-frozen-development-v2.zip).Hash.ToLower()
```

The expected value is `15e3c63da65cd1eba52ecd6d441be22d6556e9ae2008f70c652a01bb7b0eaeb2`.

Extract into the cloned repository root:

```powershell
Expand-Archive -LiteralPath .\stock-data-pipeline-frozen-development-v2.zip -DestinationPath .
```

Verify dataset availability without fetching, normalizing, regenerating, or replaying:

```bash
python -c "from research.development_dataset import load_frozen_dataset; m,q=load_frozen_dataset(); assert m['dataset_version']=='SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2'; assert m['integrity']['manifest_sha256']=='sha256:93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216'; assert len(q)==40 and sum(len(v) for v in q.values())==84284; print('FROZEN_DATASET_AVAILABLE=PASS')"
```

The archive is DEVELOPMENT_EXPOSED research input only, not Final OOS or production market data. Git remains the source-code SSOT; the release asset is the frozen binary/data archive, and the manifest/hashes are the dataset identity SSOT.
