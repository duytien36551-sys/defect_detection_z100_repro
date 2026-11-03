/* Historical BSP compile probe only; not board qualification. */
#include "xparameters.h"
#include "netif/xtopology.h"
#ifndef SDT
#error SDT topology only
#endif
_Static_assert(XPAR_XEMACPS_NUM_INSTANCES == 1, "one GEM required");
_Static_assert(XPAR_XEMACPS_0_BASEADDR == 0xe000b000U, "historical GEM0 identity");
struct xtopology_t xtopology[] = {
    { (UINTPTR)XPAR_XEMACPS_0_BASEADDR, xemac_type_emacps },
    { (UINTPTR)0, xemac_type_unknown }
};
int xtopology_n_emacs = 1;
_Static_assert(sizeof xtopology / sizeof xtopology[0] == 2, "zero sentinel");
