---
name: Streamlit authentication redirects
description: Why hosted authentication must leave a Streamlit custom-component iframe through a new top-level tab.
---

Hosted authentication launched from a Streamlit custom component must open in a user-activated top-level tab. Do not navigate the parent page directly from the component iframe.

**Why:** Streamlit sandboxes custom-component iframes without top-navigation permission. Browsers block parent-page navigation before the authentication provider is reached, leaving the login button apparently unresponsive.

**How to apply:** Open the hosted authentication URL in a new tab from the click handler. Carry any post-login action in the validated return URL so it survives the new browser and Streamlit session.