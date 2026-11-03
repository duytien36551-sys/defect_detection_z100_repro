# Export only a task-local copy of the generated Z100 project.
# The original c08a6449 project is deliberately not a valid input.
if {$argc != 2} {
    error "usage: export_xsim.tcl <task-local-project.xpr> <task-local-export-directory>"
}

proc task_physical_path {path} {
    set normalized [file normalize $path]
    if {[regexp -nocase {^([a-z]):/(.*)$} $normalized -> drive tail]} {
        if {![catch {exec -- cmd /d /c subst} mappings]} {
            set drive_pattern [format {(?i)^%s:\\:\s*=>\s*(.+?)\s*$} $drive]
            foreach mapping_line [split $mappings "\n"] {
                if {[regexp $drive_pattern [string trim $mapping_line] -> target]} {
                    set normalized [file normalize [file join [string trim $target] $tail]]
                    break
                }
            }
        }
    }
    return $normalized
}

set here [file dirname [file normalize [info script]]]
set repo_root [file normalize [file join $here .. .. .. ..]]
set build_root [file normalize [file join $repo_root deployment build z100_dma_integration]]
set build_prefix [string tolower [format "%s/" $build_root]]
set project_arg [file normalize [lindex $argv 0]]
set export_arg [file normalize [lindex $argv 1]]
set physical_project [task_physical_path $project_arg]
set physical_export [task_physical_path $export_arg]

if {![string equal -nocase [file extension $project_arg] ".xpr"] ||
    [string first $build_prefix [string tolower $physical_project]] != 0} {
    error "refusing non-task-local Vivado project: $project_arg"
}
if {[string first $build_prefix [string tolower $physical_export]] != 0} {
    error "refusing export directory outside task-local build root: $export_arg"
}
if {![file isfile $project_arg]} {
    error "task-local Vivado project is missing: $project_arg"
}
file mkdir $physical_export
set_param general.maxThreads 2
open_project -read_only $project_arg
set_property top system_wrapper [get_filesets sim_1]
export_simulation -simulator xsim -directory $export_arg -absolute_path -force
close_project
puts "Z100_SIM_TASK_LOCAL_PROJECT=$physical_project"
puts "Z100_SIM_EXPORT_DIRECTORY=$physical_export"
puts "ISOLATED_XSIM_EXPORT_PASS"
exit 0

