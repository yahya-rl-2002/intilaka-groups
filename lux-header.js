const luxuryHeader=document.querySelector('.header');
const headerLinks=[...document.querySelectorAll('.header nav>a[href^="#"]')];
function updateLuxuryHeader(){luxuryHeader.classList.toggle('scrolled',window.scrollY>12);let current='';document.querySelectorAll('main section[id]').forEach(section=>{if(section.getBoundingClientRect().top<=150)current=section.id});headerLinks.forEach(link=>link.classList.toggle('active',link.getAttribute('href')==='#'+current))}
window.addEventListener('scroll',updateLuxuryHeader,{passive:true});updateLuxuryHeader();
