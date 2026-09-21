#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
namespace fs=std::filesystem;

std::string category(const fs::path& p){
    std::string e=p.extension().string();std::transform(e.begin(),e.end(),e.begin(),::tolower);
    if(e==".jpg"||e==".jpeg"||e==".png"||e==".gif"||e==".webp")return "Images";
    if(e==".pdf"||e==".doc"||e==".docx"||e==".txt"||e==".rtf")return "Documents";
    if(e==".mp4"||e==".mov"||e==".avi"||e==".mkv")return "Videos";
    if(e==".mp3"||e==".wav"||e==".flac"||e==".m4a")return "Audio";
    if(e==".zip"||e==".rar"||e==".7z"||e==".tar"||e==".gz")return "Archives";
    if(e==".cpp"||e==".h"||e==".java"||e==".py"||e==".sql")return "Code";
    return "Other";
}
std::string sizeText(uintmax_t n){std::ostringstream s;if(n>=1024*1024)s<<std::fixed<<std::setprecision(1)<<n/(1024.0*1024)<<" MB";else if(n>=1024)s<<std::fixed<<std::setprecision(1)<<n/1024.0<<" KB";else s<<n<<" B";return s.str();}
fs::path collisionSafe(fs::path p){if(!fs::exists(p))return p;auto dir=p.parent_path(),stem=p.stem().string(),ext=p.extension().string();for(int i=1;;++i){fs::path c=dir/(stem+" ("+std::to_string(i)+")"+ext);if(!fs::exists(c))return c;}}
std::vector<fs::path> filesIn(const fs::path& dir){std::vector<fs::path> v;for(auto& e:fs::directory_iterator(dir))if(e.is_regular_file())v.push_back(e.path());std::sort(v.begin(),v.end());return v;}
void scan(const fs::path& dir){auto files=filesIn(dir);std::map<std::string,int> counts;uintmax_t total=0;std::cout<<"\nFILES\n------------------------------------------------------------\n";for(auto& p:files){auto n=fs::file_size(p);total+=n;counts[category(p)]++;std::cout<<std::left<<std::setw(32)<<p.filename().string()<<std::setw(14)<<category(p)<<sizeText(n)<<"\n";}std::cout<<"------------------------------------------------------------\n"<<files.size()<<" files • "<<sizeText(total)<<" total\n";for(auto& [c,n]:counts)std::cout<<"  "<<c<<": "<<n<<"\n";}
void organize(const fs::path& dir){auto files=filesIn(dir);std::ofstream log(dir/".fileforge_undo.log",std::ios::trunc);int moved=0;for(auto& src:files){if(src.filename()==".fileforge_undo.log"||src.filename()=="fileforge.exe")continue;fs::path folder=dir/category(src),dst=collisionSafe(folder/src.filename());fs::create_directories(folder);try{fs::rename(src,dst);log<<dst.string()<<"\t"<<src.string()<<"\n";moved++;}catch(const fs::filesystem_error& e){std::cerr<<"Could not move "<<src.filename()<<": "<<e.what()<<"\n";}}std::cout<<"Organized "<<moved<<" files.\n";}
void undo(const fs::path& dir){std::ifstream log(dir/".fileforge_undo.log");if(!log){std::cout<<"No undo record found.\n";return;}std::vector<std::pair<fs::path,fs::path>> moves;std::string line;while(std::getline(log,line)){auto t=line.find('\t');if(t!=std::string::npos)moves.push_back({line.substr(0,t),line.substr(t+1)});}int restored=0;for(auto it=moves.rbegin();it!=moves.rend();++it){if(fs::exists(it->first)){try{fs::rename(it->first,collisionSafe(it->second));restored++;}catch(...){}}}fs::remove(dir/".fileforge_undo.log");std::cout<<"Restored "<<restored<<" files.\n";}
void duplicates(const fs::path& dir){auto files=filesIn(dir);std::map<uintmax_t,std::vector<fs::path>> groups;for(auto& p:files)if(p.filename()!=".fileforge_undo.log")groups[fs::file_size(p)].push_back(p);bool found=false;std::cout<<"\nPOSSIBLE DUPLICATES (same file size)\n";for(auto& [size,v]:groups)if(v.size()>1){found=true;std::cout<<"\n"<<sizeText(size)<<":\n";for(auto& p:v)std::cout<<"  "<<p.filename().string()<<"\n";}if(!found)std::cout<<"None found.\n";std::cout<<"Note: matching size identifies candidates, not guaranteed identical content.\n";}
int main(){std::cout<<"========================================\n FileForge — C++ File Organizer\n========================================\nFolder path: ";std::string input;std::getline(std::cin,input);fs::path dir=input;if(!fs::exists(dir)||!fs::is_directory(dir)){std::cerr<<"Folder not found.\n";return 1;}while(true){std::cout<<"\n1. Scan folder\n2. Preview categories\n3. Organize files\n4. Find duplicate candidates\n5. Undo last organization\n0. Exit\nChoice: ";int choice;if(!(std::cin>>choice))break;if(choice==0)break;try{if(choice==1)scan(dir);else if(choice==2){std::cout<<"\nPREVIEW\n";for(auto& p:filesIn(dir))std::cout<<p.filename().string()<<" -> "<<category(p)<<"/\n";}else if(choice==3){std::cout<<"Organize top-level files into category folders? (y/n): ";char yes;std::cin>>yes;if(yes=='y'||yes=='Y')organize(dir);}else if(choice==4)duplicates(dir);else if(choice==5)undo(dir);}catch(const std::exception& e){std::cerr<<"Error: "<<e.what()<<"\n";}}}
