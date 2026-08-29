# Contributing

Thank you for improving GrooveMap's design system. Contributions should be reviewable in public and limited to material that can safely remain in a public repository.

## Propose and verify a change

1. Open an issue before a material change to the visual identity, asset contract, or licensing guidance.
2. Work in a focused branch or fork and keep commits small enough to review.
3. Update canonical sources in `brand/tokens.json` or `brand/templates/`, then run `just brand-render` and include the corresponding generated assets.
4. Run `just check` before opening a pull request.
5. Describe the intent, visual impact, provenance, and validation in the pull request.

Do not include credentials, private operator paths, personal identifiers, unpublished planning material, or private operational details in an issue, commit, test fixture, or pull request.

## Contribution rights

Unless separately agreed in writing, contributions are submitted under the repository's MIT License and copyright remains with the contributor. By submitting a contribution, you represent that you have the authority to provide it on those terms.

Document the source and license of any third-party asset, font, or other copyrighted material. Do not submit material with incompatible terms or unknown provenance. A contribution of copyrighted material does not grant authority over GrooveMap or third-party names, logos, or other source identifiers; follow [TRADEMARKS.md](TRADEMARKS.md) for those uses.

If a report would disclose a security vulnerability or private information, do not open a public issue. Use the private security-reporting or contact mechanism published by the GrooveMap organization, or contact a maintainer before disclosing details.
