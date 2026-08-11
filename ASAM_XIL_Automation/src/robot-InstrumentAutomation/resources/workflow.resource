*** Settings ***
Documentation     Workflow-specific statements layered on the plain-English actions in
...               actions.resource. A workflow test is just a list of instructions - the ORDER
...               of the statements is the order the teststand_api calls happen. The author
...               never lists the functions or restates the order; the backend records them.
Resource          actions.resource

*** Keywords ***
Start with a fresh bench and no hardware attached
    [Documentation]    Clear the call log and any offline sessions.
    Reset Workflow

Confirm channel ${n} on "${alias}" was set to ${volts} volts per division
    [Documentation]    Check (in English) a setting the configure step applied.
    Workflow Setting Should Be    ${alias}    ch${n}.scale    ${volts}

Save the SCPI and the recorded calls for "${alias}" to a log
    [Documentation]    Traceability: write the ordered teststand_api calls AND the SCPI they
    ...                sent to a file - the author writes none of it. The suite name is in the
    ...                filename so different flows never overwrite each other's log.
    ${suite}=    Evaluate    "${SUITE NAME}".lower().replace(" ", "_")
    ${path}=    Set Variable    ${CURDIR}/../results/scpi/workflow_${alias}_${suite}.log
    Write Workflow Scpi Log    ${alias}    ${path}
    File Should Exist    ${path}
