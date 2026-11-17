// ---- Edit these to update the site ----------------------------------------
const RATES = {
  weekday: 4999, // Monday to Friday nights
  weekend: 6999, // Saturday and Sunday nights
};

// Fill these in to show "Call" and "WhatsApp" buttons in the Book section.
// Use the full number with country code, digits only, e.g. "919876543210".
const CONTACT = {
  phone: "",
  whatsapp: "",
  email: "",
};
// ---------------------------------------------------------------------------

const inr = (n) => "₹" + n.toLocaleString("en-IN");
const isWeekend = (d) => d.getDay() === 0 || d.getDay() === 6; // Sun = 0, Sat = 6

function parseDate(value) {
  // "YYYY-MM-DD" -> local date at midnight (avoids UTC shifts)
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function toInputValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function quote(checkin, checkout, villas) {
  let weekdayNights = 0;
  let weekendNights = 0;
  for (let d = new Date(checkin); d < checkout; d.setDate(d.getDate() + 1)) {
    if (isWeekend(d)) weekendNights++;
    else weekdayNights++;
  }
  const perVilla = weekdayNights * RATES.weekday + weekendNights * RATES.weekend;
  return { weekdayNights, weekendNights, total: perVilla * villas };
}

function setupCalculator() {
  const checkin = document.getElementById("checkin");
  const checkout = document.getElementById("checkout");
  const villas = document.getElementById("villas");
  const result = document.getElementById("calc-result");

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  checkin.min = toInputValue(today);
  checkin.value = toInputValue(today);
  checkout.value = toInputValue(tomorrow);

  function render() {
    if (!checkin.value || !checkout.value) {
      result.innerHTML = "";
      return;
    }
    const inDate = parseDate(checkin.value);
    const outDate = parseDate(checkout.value);
    checkout.min = toInputValue(new Date(inDate.getTime() + 86400000));
    if (outDate <= inDate) {
      result.innerHTML = '<p class="error">Check-out must be after check-in.</p>';
      return;
    }
    const n = Number(villas.value);
    const q = quote(inDate, outDate, n);
    const parts = [];
    if (q.weekdayNights) parts.push(`${q.weekdayNights} weekday night${q.weekdayNights > 1 ? "s" : ""} × ${inr(RATES.weekday)}`);
    if (q.weekendNights) parts.push(`${q.weekendNights} weekend night${q.weekendNights > 1 ? "s" : ""} × ${inr(RATES.weekend)}`);
    result.innerHTML =
      `<p class="total">${inr(q.total)}</p>` +
      `<p class="breakdown">${parts.join(" + ")}${n > 1 ? ` × ${n} villas` : ""}</p>`;
  }

  checkin.addEventListener("change", () => {
    if (checkout.value && parseDate(checkout.value) <= parseDate(checkin.value)) {
      const next = parseDate(checkin.value);
      next.setDate(next.getDate() + 1);
      checkout.value = toInputValue(next);
    }
    render();
  });
  checkout.addEventListener("change", render);
  villas.addEventListener("change", render);
  render();
}

function setupContact() {
  const box = document.getElementById("contact-links");
  const links = [];
  if (CONTACT.phone) links.push(`<a class="btn btn-primary" href="tel:+${CONTACT.phone}">Call us</a>`);
  if (CONTACT.whatsapp) {
    const msg = encodeURIComponent("Hi, I'd like to book Aqua Heaven Resort.");
    links.push(`<a class="btn btn-ghost" href="https://wa.me/${CONTACT.whatsapp}?text=${msg}" target="_blank" rel="noopener">WhatsApp</a>`);
  }
  if (CONTACT.email) links.push(`<a class="btn btn-ghost" href="mailto:${CONTACT.email}">Email</a>`);
  box.innerHTML = links.join("");
}

function setupPhotos() {
  // Show the caption tile instead of a broken image when a photo file isn't uploaded yet.
  document.querySelectorAll(".photo img").forEach((img) => {
    const markMissing = () => img.closest(".photo").classList.add("missing");
    if (img.complete && img.naturalWidth === 0) markMissing();
    img.addEventListener("error", markMissing);
  });
}

document.getElementById("year").textContent = new Date().getFullYear();
setupPhotos();
setupCalculator();
setupContact();
