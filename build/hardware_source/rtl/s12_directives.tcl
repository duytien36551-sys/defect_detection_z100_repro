# Directives for z100_platform_s12.tcl. Sourced by BOTH stages, so whatever is
# here when the route stage starts is what route uses. Edit route= between
# stages if the post-place verdict says the job needs more router effort.
#
# Starting point, from what the S20 runs taught us:
#   opt   ExploreWithRemap - best LUT reduction seen on this design (S20 run 3)
#   place Default          - beat AltSpreadLogic_high and Explore on timing
#   phys  AggressiveExplore- more replication of high-fanout nets before hold_fix
#   route AggressiveExplore- S12 frees ~770 DSPs, so the router has room to
#                            explore; the S20 8万-overlap symptom was DSP-lock,
#                            not router effort, but extra effort is free here.
set ::z_opt_dir   ExploreWithRemap
set ::z_place_dir Default
set ::z_phys_dir  AggressiveExplore
set ::z_route_dir AggressiveExplore
