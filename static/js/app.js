// Shared JavaScript for the E-Learning Platform.

// "Show password" checkbox: reveals the password fields of its own form.
document.querySelectorAll("[data-show-passwords]").forEach(function (checkbox) {
    const passwordFields = checkbox.form.querySelectorAll("input[type='password']");
    checkbox.addEventListener("change", function () {
        passwordFields.forEach(function (field) {
            field.type = checkbox.checked ? "text" : "password";
        });
    });
});

// Forms with data-confirm="..." open the confirmation dialog before they are sent
// (used for deleting). The dialog itself is in templates/instructor/base.html.
const confirmModal = document.getElementById("confirmModal");
if (confirmModal) {
    let formToSend = null;

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            event.preventDefault();
            formToSend = form;
            document.getElementById("confirmModalMessage").textContent = form.dataset.confirm;
            bootstrap.Modal.getOrCreateInstance(confirmModal).show();
        });
    });

    document.getElementById("confirmModalButton").addEventListener("click", function () {
        if (formToSend) {
            formToSend.submit();  // submit() does not fire the "submit" event again
        }
    });
}
