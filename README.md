# PyPaaS - A Self-Healing PaaS Engine

**PyPaaS** is a lightweight Platform-as-a-Service (PaaS) engine built in Python. It mimics the core functionality of Heroku or Kubernetes, allowing for automated deployments, reverse proxy management, and self-healing of crashed containers.

## 🚀 Key Features

* **Git-Ops Deployment:** Pushing code to a Git repository triggers an automated build & deploy pipeline via Webhooks.
* **Zero-Downtime Routing:** Automatically generates Nginx configurations and manages dynamic ports, accessible via `http://app-name.localhost`.
* **Self-Healing Daemon:** A background "Healer" service monitors container health 24/7 and automatically restarts crashed applications.
* **Live Dashboard:** A real-time UI to view running applications, ports, and system status.
* **Docker-on-Docker:** Interacts directly with the low-level Docker Socket API to manage container lifecycles.

## 🛠️ Architecture

1.  **API Gateway (FastAPI):** Receives Webhooks and queues build tasks using `asyncio`.
2.  **Builder Engine:** Clones source code, builds Docker images, and manages versioning.
3.  **Proxy Manager:** Dynamically writes Nginx server blocks and reloads the proxy without dropping connections.
4.  **The Healer:** An asynchronous daemon loop that audits container state every 10 seconds.

## 📦 Tech Stack

* **Language:** Python 3.12
* **Containerization:** Docker SDK for Python
* **Web Framework:** FastAPI + Uvicorn
* **Templating:** Jinja2 (for Nginx configs & UI)
* **Proxy:** Nginx

## 🏃‍♂️ How to Run

1.  **Start the Platform:**
    ```bash
    # Install dependencies
    pip install -r requirements.txt
    
    # Start Nginx Proxy
    docker run -d --name pypaas-nginx --network host -v $(pwd)/nginx_confs:/etc/nginx/conf.d nginx
    
    # Run the Engine
    uvicorn api.server:app --reload --port 8085
    ```

2.  **Deploy an App:**
    Send a POST request to `http://localhost:8085/webhook` with your repository details.

3.  **View Dashboard:**
    Open `http://localhost:8085` in your browser.