# S.P.E.C.T.R.A. Automated HIL Validation

- Completion: **COMPLETE**
- Recorded samples: **90**
- Adaptations: **32**
- Alarms: **12**

## Stage observations

- CLEAN_DAES: 12 samples; 12 adaptations
- SOURCE_INJECTION: 12 samples; 0 adaptations
- SOURCE_RECOVERY: 12 samples; 2 adaptations
- FAULT_INJECTION: 12 samples; 0 adaptations
- FAULT_RECOVERY: 12 samples; 3 adaptations
- STATIC_MODE: 12 samples; 0 adaptations
- DAES_RECOVERY: 12 samples; 12 adaptations

## Automated checks

- all_seven_stages_observed: **PASS**
- no_adaptation_during_injection_or_static: **PASS**
- covariance_positive_definite_for_all_samples: **PASS**
- adaptation_observed_in_clean_and_recovered_DAES: **PASS**
- live_test_completed_without_manual_interruption: **PASS**

- Unsafe adaptation rows: 0
- Non-positive covariance rows: 0
- Serial parse errors: 0
- Ignored serial lines: 0

## Scientific limitations

Synthetic Poisson HIL only. No physical radiation sensor measurements, field validation, detection-accuracy claim, or validated false-alarm rate.
