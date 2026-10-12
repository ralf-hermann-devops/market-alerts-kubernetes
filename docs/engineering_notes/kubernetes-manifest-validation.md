# Kubernetes manifest validation note

CI validates Kubernetes manifests in two stages in the `application-ci.yml` workflow:

1. Kubeconform scans individual source manifests before Kustomize transformations.
2. Kustomize builds the combined manifests, which kubeconform then validates.

Kustomize patch files are not complete Kubernetes resources, so they cannot be validated meaningfully as standalone manifests. The individual-file scan therefore excludes files whose names contain `patch` (case-insensitively), as well as `kustomization.yaml`. The assembled output is still validated after Kustomize applies the patches.

Name Kustomize patch files with `patch` in the filename, for example `secret-env-patch.yaml`. This convention ensures the individual-file scan skips the patch while the combined-manifest scan still validates its effect.

## CI validation details

The `kubernetes-manifests-validation` job in `.github/workflows/application-ci.yml` checks the infrastructure target, the base, and the overlays. Kubeconform checks each target's source manifests, while `kubectl kustomize` separately builds each target so the assembled output can also be validated.

### Validation scope

The scan lints the Kubernetes resources in each Kustomize target. It reports values with incorrect types, invalid field values, and missing fields required by the resource schema. The `-strict` option also reports unknown fields and duplicate YAML keys.

The base is checked independently of overlays because an overlay may omit some base manifests; validating it separately ensures the base is valid on its own. The external infrastructure target is also checked so manual changes to those manifests are covered.

Kustomize's Helm support is enabled for the infrastructure target because KEDA is installed through a Helm chart there. The other targets do not require the Helm option.

### Kubeconform schemas and exclusions

Kubeconform uses its default schema location for standard Kubernetes resources. External custom resources are checked using an additional schema location that points to the CRD catalog in the separately maintained `datreeio/CRDs-catalog` GitHub repository.

The validation commands skip `CustomResourceDefinition` because kubeconform does not have a schema available to validate the CRD definitions themselves. Those definitions provide schemas for the custom resources, which are validated using the additional catalog.

### Individual manifest scan

Scanning each source manifest before Kustomize transformations makes schema problems easier to trace back to the file that introduced them. It also lets contributors find and fix multiple problems in a target together, rather than discovering them one at a time after building or deploying the target.

The individual scan excludes `kustomization.yaml` because it is Kustomize configuration, not a Kubernetes resource, and therefore has no Kubernetes resource schema. Patch files are also excluded: a patch is not a complete resource definition that can be validated by itself. The combined-manifest scan later validates the results after Kustomize applies those patches.

### Build and combined manifest scan

Building each target with `kubectl kustomize` catches composition errors that kubeconform's schema checks do not detect, including invalid resource references, patch targets, and Helm rendering failures. This build also produces the final YAML that is passed to kubeconform.

Kubeconform then scans the combined manifest to validate what Kustomize actually produces, including the effects of patches, generators, and transformations.
