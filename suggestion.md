1. Cryptographic Agent Authentication
In the real world, a merchant API cannot blindly trust an automated buyer script. You must secure the machine-to-machine boundary.
 * The Feature: Implement stateless authentication where the Buyer Agent must sign its cart requests using a cryptographic key.
 * The Impact: Proves you understand API security and that your financial pipeline is heavily gated against unauthorized bot traffic.
 * Execution: Generate a simple API key or JWT (JSON Web Token) for the Buyer Agent. Have your FastAPI backend strictly validate this token via dependency injection before returning any pricing data.
2. Bounded Agent-to-Agent Negotiation
Move beyond simple fetching and let the machines haggle securely.
 * The Feature: Allow the Buyer Agent to send a discount_request payload. The Merchant API evaluates this against a strict, hard-coded SQLite ruleset (e.g., "Grant 5% off if the cart exceeds ₹5,000").
 * The Impact: It demonstrates advanced A2A commerce while strictly maintaining the "bounded" requirement. The LLM never invents the discount; it only asks for one, and the Python backend mathematically enforces the boundary.
3. Ephemeral State & Cart TTL (Time-To-Live)
Hackathon projects usually ignore what happens when users abandon their sessions. Enterprise apps do not.
 * The Feature: When the Buyer Agent locks in a cart, set a 10-minute expiry timestamp in your SQLite active_carts table.
 * The Impact: Showcases graceful failure handling of asynchronous events.
 * Execution: If the human clicks the Razorpay payment link after 11 minutes, your backend intercepts the request, blocks the payment, and gracefully informs the user that the stock reservation has expired.