# LabourConnect - Platform Policies (Draft)

*This is a starting template for an academic/prototype project. Adjust terms before any real-world deployment, and have an actual legal review if this ever handles real transactions.*

## Platform Role
LabourConnect is a matching platform connecting daily wage workers with contractors/employers in rural Karnataka. It does not employ workers directly and is not a party to the employment relationship between worker and contractor.

## Fees & Pricing
For an academic prototype, a reasonable model to present is:
- **Free for workers** — no fee charged to workers for finding jobs, using the Wage Advisor, Safety Check, or Chatbot
- **Contractor listing** — contractors may post jobs for free during the pilot phase; a future monetization model could involve a small commission (e.g. 2-5%) on completed job payments, or a flat listing fee for high-visibility postings
- Position this as "currently free during pilot" if presenting to your professor, since introducing real payments raises additional legal/compliance requirements outside project scope

## Dispute Resolution
1. Worker or contractor can flag an issue via the in-app "Report Suspicious Job" feature
2. Reports are logged in Firestore for review
3. For wage disputes involving registered BOCW workers, the platform can direct users to the appropriate Labour Inspector's office
4. LabourConnect does not adjudicate disputes directly (as an academic project) but provides the reporting mechanism and relevant contact escalation information

## Data Privacy
- Worker phone numbers and profile data are used only for OTP login and job matching
- Location data is used only to match nearby jobs and is not shared with third parties
- Data is stored in Firebase per Firebase's standard security rules

## Content & Conduct
- Contractors may not post jobs that violate minimum wage law or omit safety-critical job details
- Workers found submitting false safety reports repeatedly may have their reporting privileges reviewed
- Any job posting flagged as suspicious multiple times is escalated for manual review

## Cancellation
- Either party may withdraw from a job match before work begins without penalty (given the informal, daily-wage nature of this work)
- No cancellation fee applies since this is a matching platform, not a binding contract system
