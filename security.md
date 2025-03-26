# Security Best Practices

1. **Secret Management**
   - Never commit API keys or credentials
   - Use environment variables for configuration
   - Rotate keys every 90 days
   - Use temporary credentials where possible

2. **Data Protection**
   - Encrypt sensitive health data at rest (AES-256)
   - Use TLS 1.3 for all communications
   - Anonymize patient data in logs

3. **Access Control**
   - Implement JWT authentication
   - Use role-based access control (RBAC)
   - Regularly audit permissions

4. **Audit & Monitoring**
   - Log all access to sensitive data
   - Set up intrusion detection alerts
   - Conduct quarterly penetration tests