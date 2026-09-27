# Perceptual grammar: decisions and failure modes

Use this when specifying an interface's geometry, semantic channels, state representation, or component behavior.

## Start with distinctions

Write a minimal pair for every dangerous confusion: two different real states that could produce the same reading. Decide which visual property makes the pair distinguishable **in a still frame, without relying on color alone**. Examples across domains:

| Distinction | Design implication |
| --- | --- |
| Observation vs goal vs estimate vs recommendation | Different visual identities and explicit referents; apparent certainty must track evidence. |
| Acceptable interval vs uncertainty interval | Encode the width of acceptable operation separately from uncertainty about its location. |
| Stable success vs waiting for evidence vs guidance unavailable | Distinct status and action implications, even if each calls for no immediate change. |
| Exploratory test vs supported instruction | Separate action strength, wording, and duration; do not imply both carry equal authority. |
| Current value vs change since baseline | Declare and preserve the baseline and scale; do not silently auto-rescale or clip negative change. |
| Temporary observation vs persistent instruction | Expire on changed validity, not an arbitrary toast timer; retain a valid instruction. |
| Small adjustment vs qualitatively different maneuver | Different visual and interaction treatments when the actions have different cost or risk. |

## Allocate visual channels

- **Position / angle:** Location or direction in a declared frame. A shared arc does not make different measured quantities interchangeable.
- **Distance / alignment / containment:** Relationships that would otherwise require comparing separate readings. Show operational tolerance where applicable; avoid demanding exact centering when the entire region is good.
- **Extent / band width:** Quantity or supported range, with a visible scale and valid domain. Do not use the same width for range of acceptable outcomes and uncertainty of the estimate.
- **Shape / endpoint / line pattern:** Identity and referent. Keep differences large enough to survive distance, poor lighting, and low resolution.
- **Weight / contrast / size:** Priority. Never make weak evidence look more authoritative than strong evidence solely because it is visually prominent.
- **Color:** Secondary semantic reinforcement. Do not overload one hue pair with unrelated meanings. Check grayscale and relevant color-vision conditions.
- **Text / numbers:** Use a short word when it removes costly ambiguity; use numerical precision when it changes decisions. A sparse interface can still contain essential labels.
- **Motion:** Change, urgency, or feedback. Freeze at arbitrary times and check the meaning. Never interpolate a revised inference through unsupported intermediate states.

## Component contract fields

For each significant element record: name; referent and coordinate frame; system source and age; type (observed, intended, inferred, advised); graphic and label; unit and scale; validity requirements; normal/uncertain/stale/unavailable/recovering states; interactions; transitions; priority and competing elements; persistence; and tests for likely misreadings.

Do not imply that unavailable means zero; that no recommendation means optimal; that an estimated location is a measured fact; or that a held instruction remains valid after its basis changes. Keep the current relationship visible when a recommended correction has been completed, if the relationship still matters.
