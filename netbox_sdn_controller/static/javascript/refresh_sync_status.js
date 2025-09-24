/**
 * Initializes the status update mechanism when the DOM content is fully loaded.
 */
document.addEventListener("DOMContentLoaded", function () {
    /**
     * Fetches and updates the statuses dynamically from the server.
     */
    function updateStatuses() {
        fetch(fetchStatusUrl)  // Ensure `fetchStatusUrl` is correctly defined in your environment.
            .then(response => response.json())
            .then(data => {
                // Update Fetch & Sync statuses while preserving styles
                const fetchStatusElement = document.getElementById("fetch-status");
                const syncStatusElement = document.querySelector("#sync-status span");

                // Update the fetch status text if the element exists
                if (fetchStatusElement) {
                    fetchStatusElement.innerText = data.last_fetch_status;
                }

                // Update the sync status text and adjust its class based on status
                if (syncStatusElement) {
                    syncStatusElement.innerText = data.last_sync_status;

                    // Remove any existing text color classes if you were applying them elsewhere
                    syncStatusElement.removeAttribute("class");

                    // Apply custom colors via inline style
                    if (data.last_sync_status === "completed") {
                        if (data.last_sync_job_success) {
                            syncStatusElement.style.color = "#1F857D";  // Custom green for success
                        } else {
                            syncStatusElement.style.color = "#D63939";  // Custom red for failure
                        }
                    } else {
                        syncStatusElement.style.color = "#6c757d";  // Default gray
                    }
                }

                // Enable or disable the Fetch button based on job readiness
                const fetchButton = document.getElementById("fetch-button");
                if (fetchButton) {
                    if (data.last_fetch_job_not_ready) {
                        fetchButton.setAttribute("disabled", "disabled");
                    } else {
                        fetchButton.removeAttribute("disabled");
                    }
                }

                /**
                 * Updates the badge count on a navigation tab.
                 *
                 * @param {string} linkText - The text of the tab to locate.
                 * @param {number} count - The count to display in the badge.
                 */
                function updateBadge(linkText, count) {
                    document.querySelectorAll("ul.nav-tabs .nav-link").forEach(link => {
                        if (link.textContent.includes(linkText)) {
                            let badge = link.querySelector(".badge");

                            if (count > 0) {
                                if (!badge) {
                                    // Create and append a new badge if one doesn't exist
                                    badge = document.createElement("span");
                                    badge.classList.add("badge", "text-bg-secondary");
                                    link.appendChild(badge);
                                }
                                badge.innerText = count;  // Update count
                            } else if (badge) {
                                // Remove the badge if count is zero
                                badge.remove();
                            }
                        }
                    });
                }

                // Update badge counts for various tabs
                updateBadge("Imported", data.imported_count);
                updateBadge("Discovered", data.discovered_count);
                updateBadge("Archived", data.deleted_count);
                updateBadge("Inventory", data.inventory_count);
            })
            .catch(error => console.error("Error fetching statuses:", error));
    }

    // Automatically refresh statuses every 5 seconds
    setInterval(updateStatuses, 5000);
});
