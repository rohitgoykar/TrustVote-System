# TrustVote - State Election Commission (SEC Maharashtra) Digital Voting Platform

An enterprise-grade, secure, multi-booth digital election management system engineered for the **State Election Commission of Maharashtra**.

---

## 🌟 Key Architecture & Features

### 1. 🔒 Immutable SHA-256 Blockchain Security Ledger
* **Cryptographic Block Chaining**: Every vote cast is recorded in a tamper-evident SHA-256 blockchain block linked directly to previous block hashes.
* **Zero-Knowledge Voter Privacy**: Voter IDs are cryptographically hashed and anonymized on-chain to ensure ballot secrecy while providing 100% public auditability.
* **Algorithmic Chain Verification**: Recursive hash verification algorithm validating block integrity from Genesis block #0 to the latest block.

### 2. 🗺️ Interactive Maharashtra District-Wise Telemetry Map
* **SVG Vector Map**: Covers all 36 Maharashtra Districts across all 6 Administrative Divisions (*Pune, Konkan, Nashik, Chhatrapati Sambhajinagar / Marathwada, Amravati, Nagpur*).
* **Live Participation Heatmap**: Real-time district voter turnout spotlights, live radar beacons, and cascading jurisdiction filtering.

### 3. 🏛️ Multi-Tier Local Body Election Cycles
* Full native support for Maharashtra Local Body elections:
  * ग्रामपंचायत (Gram Panchayat)
  * पंचायत समिती (Panchayat Samiti)
  * जिल्हा परिषद (Zilha Parishad)
  * महानगरपालिका (Mahanagarpalika)
  * नगरपालिका / नगरपरिषद (Nagar Parishad)
  * नगरपंचायत (Nagar Panchayat)
* Cross-Constituency and Multi-Ward duplicate voting prevention.

### 4. 📷 Multi-Strategy Resilient QR Decoder & Face Authentication
* Multi-strategy pouch-cropping and CLAHE contrast enhancement for QR scanning.
* DeepFace / Facenet biometric face authentication.
* Standalone **Official Voting Pass** and dual-sided **Election Photo Identity Card**.

---

## 🚀 Quick Start Guide

### Prerequisites
* Python 3.9+
* Recommended: `pip install -r requirements.txt`

### Running the Application
```bash
python app.py
```
* **Main Election Officer Control Center**: `http://localhost:5000/admin/dashboard` *(Login: `admin` / `admin123`)*
* **Citizen Registration Portal**: `http://localhost:5000/register_page` *(Login: `officer1` / `officer123`)*
* **Polling Booth Scanner**: `http://localhost:5000/scan` *(Login: `booth1` / `booth123`)*

---

## 📤 Push to GitHub

Run `push_to_github.bat` or execute:
```bash
git init
git add .
git commit -m "Initial Release: SEC Maharashtra TrustVote Blockchain Voting Platform"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```
