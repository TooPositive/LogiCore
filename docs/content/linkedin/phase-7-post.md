# Phase 7 LinkedIn Post: Resilience Engineering — Circuit Breakers, Model Routing

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

Friday, 2:47 AM. Azure OpenAI starts returning 503s. Five requests fail in 60 seconds. Nobody in the logistics company notices coz the AI switches itself to the local model and keeps answering.

This is Phase 7 of a 12-phase AI system im building for a logistics company. Phase 1 proved embeddings are mandatory for search. Phase 4 cut AI costs 93% with model routing. Phase 6 made the whole pipeline run on a local model without changing a line of code. Phase 7 asks a different question: what happens when your primary provider goes down at 3 AM and your fleet monitoring dashboard feeds answers to dispatchers making EUR 180,000 cargo decisions?

The circuit breaker pattern isnt new. But most implementations I see only count HTTP errors. Thats maybe 60% of real outages. The other 40%? Provider returns 200 OK with an empty string. Or a response thats just whitespace. Or (this one took me a while to find) unicode zero-width spaces that pass Pythons len() check but contain literally zero visible characters. Your monitoring shows all green. Your users get nothing. EUR 500-5,000 per incident in wrong business decisions based on empty responses.

The quality gate strips whitespace AND six specific invisible unicode characters before checking length. Pythons str.strip() does not handle U+200B (zero-width space) or U+FEFF (byte order mark). Found that during code review, not in production. Thats the kind of gap you only find when someone asks "but what if the response looks long but is actually empty?"

What I chose NOT to build: a single monolithic retry-then-failover loop. Instead, retry lives INSIDE each provider (retry Azure 3x with exponential backoff + jitter), and THEN the chain moves to the next healthy provider. The difference matters when Azure is flaky but not fully dead. A cascade-level retry would keep bouncing back to the dying provider after each successful Ollama call. Per-provider retry exhausts Azure's retries once, then moves on permanently until the circuit breaker probes again after 60s.

The cost model was the part I expected to be simple and ended up stress-testing. 83.5% savings sounds amazing right? EUR 2.28/day vs EUR 14.00/day at 1000 queries, routing simple lookups ("whats the status of truck-0892") to GPT-5 nano at EUR 0.0004 instead of GPT-5.2 at EUR 0.014. But that number assumes 70% of queries are simple. So I tested six different distributions. At 50/30/20 (balanced), savings are still ~68%. At 30/30/40 (complex-heavy), ~45%. Routing only stops making sense when >90% of queries need the expensive model, and if thats your distribution, routing isnt your problem. Prompt engineering is.

The one thing I got wrong initially: degraded mode governance. The circuit breaker switches to the fallback, the fallback answers, everyone's happy. Except the fallback might have lower accuracy on financial queries. And Phase 3's invoice auditor has an auto-approve band for discrepancies under EUR 50. You dont want auto-approved financial decisions running through a degraded model at 3 AM. The response now carries an `is_degraded` flag and the auto-approve path checks it. Degraded = force human review, always.

What breaks: the failover time is architectural, not measured. Skipping a tripped circuit breaker is effectively free (no network call) so I say <100ms, but I havent instrumented it under real load. Phase 12 will. Also the cost sensitivity analysis assumes a query distribution that hasnt been validated against production data yet. Both are honest unknowns.

Post 7/12 in the LogiCore series. Next up: what happens when EU regulators ask for an audit trail of every AI decision your system ever made.

---

## Reply Ammo

**"Circuit breakers are basic. Everyone uses them."**
yeah the state machine itself is basic. The interesting part is WHAT counts as a failure. Most implementations count HTTP errors. None that ive seen count "200 OK with invisible unicode characters" as a failure. Thats the gap between a pattern and a production implementation.

**"Why not just use a load balancer?"**
A load balancer distributes across healthy nodes. A circuit breaker detects that a node is unhealthy and stops sending traffic. Different concern. You need both, but the breaker is the one that prevents 60-second timeouts hitting your users.

**"83.5% savings seems inflated"**
Fair. Thats at 70/20/10 query distribution (simple/medium/complex). Stress-tested across 6 distributions. At 30/30/40 its still ~45%. At 10/20/70 its ~20%. The crossover where routing adds overhead without benefit is >90% complex. I havent seen a logistics company where >90% of queries need GPT-5.2.

**"Why not use a managed service like Azure's circuit breaker?"**
Vendor lock-in. The whole point of Phase 6 was making the system provider-agnostic. A managed Azure circuit breaker doesnt help when Azure IS the provider thats down.

**"What about the quality degradation during failover?"**
Thats exactly why the is_degraded flag exists. The system doesnt pretend fallback quality equals primary quality. It marks the response, the downstream auto-approve path checks it, financial decisions get forced to human review. Honest degradation > invisible degradation.

**"Isn't the quality gate too simple? Just checking response length?"**
Surprisingly effective for the failure mode it targets. 200-OK-garbage isnt adversarial (thats Phase 10's job). Its a provider returning nothing during partial degradation. Length check after stripping invisible chars catches that at zero latency cost. More sophisticated content analysis would add latency for a problem that doesnt need it.

**"How do you handle rate limiting (429) vs real failures?"**
429 counts as a retriable failure with the retry policy. The retry respects exponential backoff. If you burn through all retries (3 by default), then the circuit breaker counts it as a provider failure. 5 of those trip the breaker. So rate limiting causes a graceful slow-down before triggering failover.

**"Why extract the circuit breaker from the reranker instead of having two implementations?"**
Coz I already had a circuit breaker in Phase 2's reranker. Same state machine, same pattern, different wrapper. Extracting saved ~60 lines and means any future service (embedding provider, database, whatever) gets circuit breaking for free. Two implementations = two places to fix bugs.

**"The 200-OK-garbage problem sounds made up."**
Wish it was. Azure has had partial degradation events where the endpoint responds with 200 but empty or truncated content. The monitoring dashboard shows zero errors. Your users see "AI is responding" but the responses are empty. Support tickets pile up while your metrics look perfect.

**"What happens if both Azure AND Ollama are down?"**
Cache. The last-resort is the RBAC-partitioned semantic cache from Phase 4. It serves the closest matching previous answer with a disclaimer: "this response is from cache, live providers are unavailable." Not ideal but better than an error page. The cache is RBAC-safe by construction (partitioned by clearance level + departments) so theres no cross-tenant leakage risk.
