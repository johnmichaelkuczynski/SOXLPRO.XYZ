---
name: ARM64 Python wheel resolution
description: Cross-platform pip resolution for ARM64 Docker images built on amd64.
---

When installing ARM64 Python wheels from an amd64 Docker build stage, pass multiple compatible manylinux platform tags. A lone `manylinux_2_28_aarch64` tag failed to resolve wheels published as `manylinux_2_17_aarch64`; including compatible 2_17, 2_24, 2_27, 2_28, and manylinux2014 tags allowed the full dependency set to install.

**Why:** pip's cross-platform tag resolution in this builder did not infer every backward-compatible manylinux tag from one newer tag.

**How to apply:** when adding or upgrading Python dependencies, rebuild both linux/amd64 and linux/arm64 images and verify the reported target architecture.
